"""resume: PDF import (Claude mocked, plain parser) and the experience bank."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "resume"))
import bankdata  # noqa: E402
from minipdf import ALEX_RESUME, make_pdf  # noqa: E402

from applyfirst import claude, config, store  # noqa: E402
from applyfirst.resume import bank, import_pdf, parse  # noqa: E402


@pytest.fixture
def alex_pdf(tmp_path):
    return make_pdf(ALEX_RESUME, str(tmp_path / "alex.pdf"))


@pytest.fixture
def no_claude(monkeypatch):
    calls = []

    def run(prompt, run_id=None, **kw):
        calls.append(prompt)
        return claude.Result(False, error="Claude Code is not installed or not on PATH.")
    monkeypatch.setattr(claude, "run", run)
    return calls


def by_section(rows, section):
    return [r for r in rows if r["section"] == section and not r["parent_id"]]


def bullets_of(rows, entry_id):
    return [r for r in rows if r["parent_id"] == entry_id]


# ------------------------------------------------------------------ plain parser


def test_plain_parser_finds_sections_entries_and_bullets(tmp_home, alex_pdf, no_claude):
    rows = import_pdf(alex_pdf)
    assert all(r["confirmed"] == 0 for r in rows)
    jobs = by_section(rows, "experience")
    assert [(j["title"], j["org"], j["dates"]) for j in jobs] == [
        ("Software Intern", "Northwind Labs", "May 2026 - Aug 2026"),
        ("Teaching Assistant", "Example University", "Sep 2025 - Dec 2025")]
    first = bullets_of(rows, jobs[0]["id"])
    assert len(first) == 3
    assert first[0]["text"] == ("Built a REST API in Python and FastAPI that cut report generation time "
                                "from 40 seconds to 6 seconds")
    assert "python" in first[0]["tags"] and "fastapi" in first[0]["tags"]
    assert "role:software" in first[0]["tags"]
    edu = by_section(rows, "education")[0]
    assert (edu["title"], edu["org"]) == ("BEng Computer Engineering", "Example University")
    projects = by_section(rows, "projects")
    assert [p["title"] for p in projects] == ["Smart Plant Monitor", "Budget Tracker"]
    assert [r["org"] for r in by_section(rows, "skills") if r["title"] == "Python"] == ["Languages"]
    assert by_section(rows, "other")[0]["title"] == "Robotics Club"


def test_import_falls_back_when_claude_is_missing_and_stores_in_bank(tmp_home, alex_pdf, no_claude):
    import_pdf(alex_pdf)
    assert len(no_claude) == 1                      # Claude was tried first
    assert store.one("SELECT COUNT(*) AS n FROM experience")["n"] > 20
    assert not bank.has_confirmed()


def test_import_fills_blank_profile_but_never_overwrites(tmp_home, alex_pdf, no_claude):
    import_pdf(alex_pdf)
    p = config.load_profile()
    assert (p["name"]["first"], p["name"]["last"]) == ("Alex", "Rivera")
    assert p["email"] == "alex.rivera@example.com" and p["links"]["github"] == "https://github.com/example"
    p["name"]["first"] = "Sam"
    p["email"] = "sam@example.com"
    config.save_profile(p)
    import_pdf(alex_pdf)
    p = config.load_profile()
    assert p["name"]["first"] == "Sam" and p["email"] == "sam@example.com"


def test_wrapped_bullet_lines_are_joined(tmp_home, tmp_path, no_claude):
    lines = ["JORDAN LEE", "jordan@example.com", "EXPERIENCE",
             "Developer, Acme Corp          Jan 2025 - Present",
             "- Designed and shipped a customer facing dashboard that tracks order status in real time for the",
             "  support team across three regions and two time zones",
             "- Short bullet one",
             "PROJECTS",
             "Chess Engine",
             "- Wrote a move generator in Rust that searches six plies deep in under a second per move today"]
    rows = import_pdf(make_pdf(lines, str(tmp_path / "w.pdf")))
    jobs = by_section(rows, "experience")
    assert len(jobs) == 1
    texts = [b["text"] for b in bullets_of(rows, jobs[0]["id"])]
    assert texts[0].endswith("two time zones") and "the support team" in texts[0]
    assert texts[1] == "Short bullet one"
    assert by_section(rows, "projects")[0]["title"] == "Chess Engine"


def test_scanned_pdf_gives_a_plain_error(tmp_home, tmp_path):
    p = make_pdf([""], str(tmp_path / "blank.pdf"))
    with pytest.raises(ValueError, match="no readable text"):
        import_pdf(p)


# ------------------------------------------------------------------ Claude path


def test_claude_structured_answer_is_used_and_tags_mapped(tmp_home, alex_pdf, monkeypatch):
    seen = {}

    def run(prompt, run_id=None, **kw):
        seen["schema"] = kw.get("json_schema")
        seen["prompt"] = prompt
        return claude.Result(True, structured={
            "contact": {"name": "Alex Rivera", "email": "alex.rivera@example.com"},
            "entries": [{"section": "experience", "title": "Software Intern", "org": "Northwind Labs",
                         "dates": "May 2026 - Aug 2026", "bullets": [
                             {"text": "Wrote 120 unit tests with pytest and set up continuous integration "
                                      "on GitHub Actions", "skills": ["Python"], "tools": ["pytest"],
                              "role_types": ["software", "not-a-role"]},
                             {"text": "Cut cloud costs by 90 percent", "skills": [], "tools": [],
                              "role_types": []}]}],
            "skills": [{"group": "Languages", "items": ["Python", "C++"]}]})
    monkeypatch.setattr(claude, "run", run)
    rows = import_pdf(alex_pdf)
    assert seen["schema"]["required"] == ["entries"]
    assert "EXACTLY" in seen["prompt"] and "ALEX RIVERA" in seen["prompt"]
    jobs = by_section(rows, "experience")
    assert len(jobs) == 1
    b1, b2 = bullets_of(rows, jobs[0]["id"])
    assert b1["tags"] == ["pytest", "python", "role:software"]
    # a line that is not in the PDF is flagged for the user's review, never silently trusted
    assert "needs-review" in b2["tags"] and "needs-review" not in b1["tags"]
    assert [r["title"] for r in by_section(rows, "skills")] == ["Python", "C++"]


@pytest.mark.parametrize("answer", [
    claude.Result(False, error="boom"),
    claude.Result(True, structured={"entries": []}),
    claude.Result(True, structured={"nonsense": 1}),
    claude.Result(True, structured=None),
])
def test_unusable_claude_answers_fall_back_to_plain_parser(tmp_home, alex_pdf, monkeypatch, answer):
    monkeypatch.setattr(claude, "run", lambda *a, **k: answer)
    rows = import_pdf(alex_pdf)
    assert by_section(rows, "experience")[0]["title"] == "Software Intern"


def test_claude_exception_falls_back_and_is_logged(tmp_home, alex_pdf, monkeypatch):
    def run(*a, **k):
        raise OSError("disk on fire")
    monkeypatch.setattr(claude, "run", run)
    rid = store.start_run("resume")
    rows = import_pdf(alex_pdf, rid)
    assert by_section(rows, "experience")
    log = Path(store.one("SELECT log_file FROM runs WHERE id=?", (rid,))["log_file"]).read_text(encoding="utf-8")
    assert "disk on fire" in log and "plain parser" in log


# ------------------------------------------------------------------ the bank


def test_reimport_replaces_unconfirmed_and_keeps_confirmed(tmp_home, alex_pdf, no_claude):
    import_pdf(alex_pdf)
    n = store.one("SELECT COUNT(*) AS n FROM experience")["n"]
    import_pdf(alex_pdf)                                 # unconfirmed rows replaced, not doubled
    assert store.one("SELECT COUNT(*) AS n FROM experience")["n"] == n
    bank.confirm_all()
    import_pdf(alex_pdf)                                 # everything is already confirmed: nothing added
    assert store.one("SELECT COUNT(*) AS n FROM experience")["n"] == n
    assert all(r["confirmed"] == 1 for r in bank.all_rows())


def test_confirm_edit_delete_and_ids(tmp_home):
    e = bank.add({"section": "experience", "title": "Barista", "org": "Cafe", "confirmed": 0})
    assert e["id"] == "E1"
    b1 = bank.add({"parent_id": "E1", "text": "Served 200 customers a day"})
    b2 = bank.add({"parent_id": "E1", "text": "Trained two new hires"})
    assert (b1["id"], b2["id"]) == ("E1.b1", "E1.b2")
    assert bank.add({"section": "projects", "title": "Blog"})["id"] == "E2"
    assert bank.load(True) == []                          # nothing confirmed yet
    assert bank.update("E1", {"confirmed": True})["confirmed"] == 1
    # bullets stay out until confirmed themselves, even when their entry is
    assert [b["id"] for e in bank.load(True) if e["id"] == "E1" for b in e["bullets"]] == []
    assert bank.confirm_all() >= 2
    assert len([b for e in bank.load(True) if e["id"] == "E1" for b in e["bullets"]]) == 2
    assert bank.update("E1.b1", {"text": "Served 250 customers a day", "tags": ["service"]})["tags"] == ["service"]
    assert bank.delete("E1")
    assert bank.get("E1.b1") is None                      # bullets go with their entry
    assert bank.delete("nope") is False
    with pytest.raises(ValueError):
        bank.add({"section": "bogus"})


def test_unconfirmed_rows_never_reach_the_model(tmp_home):
    bankdata.seed(confirmed=False)
    assert bank.load(True) == [] and not bank.has_confirmed()
    assert len(bank.load(False)) > 10
