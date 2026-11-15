"""resume: cover letters. Claude is mocked; the checks around it are real."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "resume"))
import bankdata  # noqa: E402

from applyfirst import claude, config, store  # noqa: E402
from applyfirst import resume  # noqa: E402
from applyfirst.resume import bank, provenance, render, style  # noqa: E402

POSTING = {"id": "p1", "company": "Acme Robotics", "title": "Firmware Intern", "location": "Toronto, ON",
           "description": "Acme Robotics builds warehouse robots. You will write C++ firmware for sensors and "
                          "debug hardware with Verilog simulations."}

GOOD = {"paragraphs": [
    "I am applying for the Firmware Intern role at Acme Robotics. Last summer at Northwind Labs I built a "
    "REST API in Python that cut report generation time from 40 seconds to 6 seconds.",
    "In my Smart Plant Monitor project I wrote the firmware in C++ for an Arduino sensor network, and as a "
    "teaching assistant I graded Verilog and FPGA design work."],
    "evidence": [{"sentence": "I built a REST API", "bank_ids": ["E2.b1"]},
                 {"sentence": "I wrote the firmware in C++", "bank_ids": ["E4.b2"]}]}


@pytest.fixture
def seeded(alex):
    return bankdata.seed()


@pytest.fixture
def writer(monkeypatch):
    """Mock applyfirst.claude.run; `writer.answers` is consumed one per call."""
    state = type("S", (), {"answers": [], "prompts": []})()

    def run(prompt, run_id=None, **kw):
        state.prompts.append(prompt)
        return claude.Result(True, structured=state.answers.pop(0))
    monkeypatch.setattr(claude, "run", run)
    return state


def test_no_posting_body_gives_none_without_calling_claude(seeded, writer):
    assert resume.cover_letter({**POSTING, "description": ""}) is None
    assert resume.cover_letter({**POSTING, "description": "   \n"}) is None
    assert writer.prompts == []


def test_good_letter_is_written_as_a_pdf_named_for_company_and_role(seeded, writer):
    writer.answers = [GOOD]
    path = resume.cover_letter(POSTING)
    assert path and Path(path).exists()
    assert Path(path).name == "Alex_Rivera_Cover_Letter_Acme_Robotics_Firmware_Intern.pdf" or path.endswith(".html")
    assert len(writer.prompts) == 1
    # the writer sees the bank and the posting, with the hard rules
    assert "E2.b1" in writer.prompts[0] and "Acme Robotics builds warehouse robots" in writer.prompts[0]
    assert "ONLY facts from THE BANK" in writer.prompts[0]
    meta = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["letter"] is True and meta["evidence"]
    text = render.pdf_text(path) if path.endswith(".pdf") else Path(path).read_text(encoding="utf-8")
    assert "Dear Acme Robotics Hiring Team," in text and "Sincerely," in text
    assert "—" not in text
    assert path in [str(Path(builder_dir) / f["name"]) for f in resume.list_files()
                    for builder_dir in [config.path("resumes")]]


def test_letter_with_an_invented_number_is_retried_then_kept_if_fixed(seeded, writer):
    bad = {"paragraphs": ["I built a REST API that cut report time by 95 percent at Northwind Labs."],
           "evidence": [{"sentence": "x", "bank_ids": ["E2.b1"]}]}
    writer.answers = [bad, GOOD]
    path = resume.cover_letter(POSTING)
    assert path
    assert len(writer.prompts) == 2
    assert "95" in writer.prompts[1] and "YOUR LAST DRAFT HAD THESE PROBLEMS" in writer.prompts[1]


def test_letter_that_stays_untrue_is_dropped(seeded, writer):
    bad = {"paragraphs": ["At Initech I led a team of 40 engineers and shipped Kubernetes clusters."],
           "evidence": [{"sentence": "x", "bank_ids": ["E2.b1"]}]}
    writer.answers = [bad, bad]
    rid = store.start_run("resume")
    assert resume.cover_letter(POSTING, rid) is None
    log = Path(store.one("SELECT log_file FROM runs WHERE id=?", (rid,))["log_file"]).read_text(encoding="utf-8")
    assert "dropped" in log and "Initech" in log


def test_evidence_must_point_at_real_bank_rows(seeded, writer):
    ghost = {**GOOD, "evidence": [{"sentence": "x", "bank_ids": ["E99.b9"]}]}
    writer.answers = [ghost, ghost]
    assert resume.cover_letter(POSTING) is None


def test_a_true_draft_survives_a_failed_style_retry(seeded, writer):
    stocky = {**GOOD, "paragraphs": [GOOD["paragraphs"][0] + " I am passionate about robotics.",
                                     GOOD["paragraphs"][1]]}
    worse = {"paragraphs": ["I led 12 teams at Initech."], "evidence": GOOD["evidence"]}
    writer.answers = [stocky, worse]
    path = resume.cover_letter(POSTING)
    assert path                                            # the first draft was true; keep it
    meta = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))
    assert any("passionate" in n for n in meta["style_notes"])


def test_claude_failure_means_no_letter_not_a_made_up_one(seeded, monkeypatch):
    monkeypatch.setattr(claude, "run", lambda *a, **k: claude.Result(False, error="not installed"))
    assert resume.cover_letter(POSTING) is None


def test_empty_bank_is_a_plain_error(alex, writer):
    with pytest.raises(resume.BankEmpty):
        resume.cover_letter(POSTING)


def test_claim_checker_unit(seeded):
    entries, profile = bank.load(True), config.load_profile()
    ok = ["I built a REST API in Python and FastAPI at Northwind Labs for Acme Robotics."]
    assert provenance.check_letter(ok, entries, POSTING, profile) == []
    problems = provenance.check_letter(["I scaled it to 3 million users on AWS."], entries, POSTING, profile)
    assert any("3" in p for p in problems) and any("AWS" in p for p in problems)
    # a sentence-initial capital is grammar, not a claim
    assert provenance.check_letter(["Firmware matters to me."], entries, POSTING, profile) == []


def test_style_check_ports_the_stock_phrase_list():
    assert style.style_findings("I am passionate about innovative robotics.")
    assert style.style_findings("We leverage a proven track record.")
    assert style.style_findings("I will navigate and foster growth.")           # two weak words together
    assert style.style_findings("I will navigate the codebase.") == []          # one alone is fine
    assert style.style_findings("I wrote the firmware for the sensor board and tested it on a bench.") == []
