"""resume: choosing lines, rendering one page, and checking the result against the bank."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "resume"))
import bankdata  # noqa: E402
from minipdf import make_pdf  # noqa: E402

from applyfirst import config  # noqa: E402
from applyfirst import resume  # noqa: E402
from applyfirst.resume import bank, provenance, render, tailor  # noqa: E402

needs_browser = pytest.mark.skipif(render.find_browser() is None, reason="no Chrome, Edge or Chromium here")


@pytest.fixture
def seeded(alex):
    return bankdata.seed()


def sections(chosen):
    return [p["section"] for p in chosen]


# ------------------------------------------------------------------ selection (pure)


def test_relevance_reorders_inside_a_section_never_across(seeded):
    entries = bank.load(True)
    sw, _ = tailor.select(entries, {"react", "typescript"}, None)
    hw, _ = tailor.select(entries, {"arduino"}, None)
    titles = lambda chosen, sec: [p["title"] for p in chosen if p["section"] == sec]  # noqa: E731
    assert titles(sw, "projects") == ["Budget Tracker", "Smart Plant Monitor"]
    assert titles(hw, "projects") == ["Smart Plant Monitor", "Budget Tracker"]
    for chosen in (sw, hw):
        order = [tailor.SECTION_ORDER.index(s) for s in sections(chosen)]
        assert order == sorted(order)                      # sections never interleave


def test_role_type_promotes_tagged_bullets(seeded):
    entries = bank.load(True)
    chosen, _ = tailor.select(entries, set(), "hardware", max_bullets={"experience": 1})
    ta = next(p for p in chosen if p["title"] == "Teaching Assistant")
    assert [b["text"] for b in ta["selected"]] == ["Ran weekly labs on digital logic for 60 first-year students"]
    swe, _ = tailor.select(entries, set(), "software", max_bullets={"experience": 1})
    assert next(p for p in swe if p["title"] == "Software Intern")["selected"][0]["text"].startswith("Built a REST API")


def test_overflow_never_drops_experience_or_always_bullets(seeded):
    ids = seeded
    bank.update(ids["intern"] + ".b3", {"tags": ["sql", "always"]})
    entries = bank.load(True)
    chosen, _ = tailor.select(entries, set(), None)
    exp_before = [p["id"] for p in chosen if p["section"] == "experience"]
    steps = []
    while (s := tailor.fit_step(chosen)) is not None:
        steps.append(s)
    assert steps, "something should have been trimmed"
    assert [p["id"] for p in chosen if p["section"] == "experience"] == exp_before
    intern = next(p for p in chosen if p["id"] == ids["intern"])
    assert ids["intern"] + ".b3" in [b["id"] for b in intern["selected"]]
    assert all(p["selected"] for p in chosen if p["section"] == "experience")     # never a bare heading
    assert tailor.drop_victim([p for p in chosen if p["section"] == "experience"]) is None


def test_pinned_entry_is_not_dropped_and_leads_its_section(seeded):
    ids = seeded
    bank.update(ids["plant"], {"tags": ["pinned", "role:hardware"]})
    chosen, _ = tailor.select(bank.load(True), {"react", "typescript"}, None)
    projects = [p for p in chosen if p["section"] == "projects"]
    assert projects[0]["id"] == ids["plant"]               # pinned leads despite lower relevance
    assert tailor.drop_victim(projects)["id"] != ids["plant"]


def test_technical_skills_short_rule(seeded):
    entries = bank.load(True)
    chosen, _ = tailor.select(entries, set(), None)
    groups = dict(tailor.pick_skills(entries, chosen, set()))
    printed = {t for items in groups.values() for t in items}
    assert "Rust" not in printed and "Docker" not in printed      # no bullet on the page uses them
    assert "Python" in printed
    assert len(groups["Languages"]) <= tailor.SKILL_CAP_LANGUAGES
    # when the posting asks for a term and a bullet uses it, it ranks first
    groups = dict(tailor.pick_skills(entries, chosen, {"verilog"}))
    assert groups["Languages"][0] == "Verilog"
    # asking for a term nothing on the page uses does not put it on the page
    assert "Rust" not in dict(tailor.pick_skills(entries, chosen, {"rust"})).get("Languages", [])


def test_wanted_terms_come_only_from_the_bank():
    entries = [{"id": "E1", "section": "skills", "title": "Python", "org": "Languages", "dates": "",
                "tags": [], "bullets": []}]
    posting = {"title": "Engineer", "description": "We use Python and Haskell, not C."}
    assert tailor.wanted_terms(posting, entries) == {"python"}


def test_duplicate_claim_is_caught_within_one_entry_and_picker_avoids_it():
    e = {"id": "E1", "selected": [
        {"id": "E1.b1", "text": "Built a test suite with 11 Playwright specs"},
        {"id": "E1.b2", "text": "Ran 11 Playwright specs on every commit"}]}
    assert tailor.duplicate_claims([e]) and "E1.b1 and E1.b2" in tailor.duplicate_claims([e])[0]
    other = {"id": "E2", "selected": [{"id": "E2.b1", "text": "Ran 11 Playwright specs"}]}
    assert tailor.duplicate_claims([{**e, "selected": e["selected"][:1]}, other]) == []   # across entries is fine
    entry = {"id": "E1", "section": "projects", "title": "T", "org": "", "dates": "", "tags": [],
             "bullets": [{"id": "E1.b1", "text": "Built a suite with 11 Playwright specs", "tags": ["playwright"]},
                         {"id": "E1.b2", "text": "Ran 11 Playwright specs nightly", "tags": ["playwright"]},
                         {"id": "E1.b3", "text": "Wrote a deploy script", "tags": []}]}
    chosen, _ = tailor.select([entry], {"playwright"}, None, max_bullets={"projects": 2})
    assert [b["id"] for b in chosen[0]["selected"]] == ["E1.b1", "E1.b3"]
    assert tailor.duplicate_claims(chosen) == []


# ------------------------------------------------------------------ provenance (no browser needed)


def bank_lines():
    return ["Alex Rivera", "Toronto, Ontario | 555-0100 | alex.rivera@example.com", "EXPERIENCE",
            "Software Intern, Northwind Labs May 2026 - Aug 2026",
            "Wrote 120 unit tests with pytest and set up continuous integration on GitHub Actions",
            "Migrated three internal tools from SQLite to PostgreSQL without downtime"]


def test_verify_accepts_a_page_made_only_of_bank_lines(seeded, tmp_path):
    pdf = make_pdf(bank_lines(), str(tmp_path / "ok.pdf"))
    assert resume.verify(pdf) == []


def test_verify_catches_a_fabricated_bullet(seeded, tmp_path):
    """The invariant is checked from outside the generator: plant a line that is not in the bank."""
    lines = bank_lines() + ["Increased company revenue by 400 percent in one quarter"]
    problems = resume.verify(make_pdf(lines, str(tmp_path / "bad.pdf")))
    assert problems and "revenue by 400 percent" in problems[0]
    # even a short fabricated claim does not slip through
    short = resume.verify(make_pdf(bank_lines() + ["Led a team of 12 engineers"], str(tmp_path / "bad2.pdf")))
    assert short


def test_verify_ignores_unconfirmed_rows(alex, tmp_path):
    bankdata.seed(confirmed=True)
    bank.add({"parent_id": "E2", "text": "Shipped a self-driving car to production", "confirmed": 0})
    lines = bank_lines() + ["Shipped a self-driving car to production"]
    assert resume.verify(make_pdf(lines, str(tmp_path / "u.pdf")))


def test_verify_reports_an_empty_bank_and_unreadable_pdf(alex, tmp_path):
    assert "no confirmed" in resume.verify(str(tmp_path / "x.pdf"))[0]
    bankdata.seed()
    assert "No such file" in resume.verify(str(tmp_path / "missing.pdf"))[0]


def test_ats_check_flags_missing_heading_and_contact(seeded, tmp_path):
    good = make_pdf(["Alex Rivera", "alex.rivera@example.com 555-0100", "EXPERIENCE"]
                    + [f"Built thing number {i} with care and attention" for i in range(8)],
                    str(tmp_path / "g.pdf"))
    profile = config.load_profile()
    assert provenance.ats_problems(good, profile, ["Experience"]) == []
    bad = make_pdf(["Alex Rivera EXPERIENCE Built a thing"] + [f"line {i} text goes here ok" for i in range(8)],
                   str(tmp_path / "b.pdf"))
    problems = provenance.ats_problems(bad, profile, ["Experience"])
    assert any("Experience" in p for p in problems) and any("email" in p for p in problems)
    image_only = make_pdf([" "], str(tmp_path / "i.pdf"))
    assert "extractable text" in provenance.ats_problems(image_only, profile, [])[0]


# ------------------------------------------------------------------ building


@needs_browser
def test_build_makes_one_clean_page_named_for_the_user(seeded):
    res = resume.build_detailed()
    assert Path(res.path).name == "Alex_Rivera_Resume.pdf" and res.kind == "pdf"
    assert res.pages == 1 and res.clean, (res.problems, res.ats_problems)
    assert resume.verify(res.path) == []
    meta = json.loads(Path(res.path).with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["verified"] is True and meta["problems"] == []
    assert resume.build() == res.path                      # the contract call returns the same path


@needs_browser
def test_selftest_injected_fabrication_in_a_real_render_is_caught(seeded):
    """Render a real page with one bullet that is NOT in the bank; the PDF check must flag it."""
    profile = config.load_profile()
    entries = bank.load(True)
    chosen, _ = tailor.select(entries, set(), None)
    chosen[0]["selected"].append({"id": "X.b1", "tags": [],
                                  "text": "Founded a startup that was acquired for forty million dollars"})
    html = render.render_html(profile, chosen, tailor.pick_skills(entries, chosen), True)
    tmp = Path(config.home()) / "fab"
    tmp.mkdir()
    (tmp / "f.html").write_text(html, encoding="utf-8")
    ok, err = render.render_pdf(str(tmp / "f.html"), str(tmp / "f.pdf"))
    assert ok, err
    problems = resume.verify(str(tmp / "f.pdf"))
    assert problems and "acquired for forty million" in problems[0]
    assert provenance.verify_pdf(str(tmp / "f.pdf"), entries, profile, chosen)   # also flags the chosen list


@needs_browser
def test_overflow_trims_to_one_page_and_keeps_every_experience_entry(alex):
    ids = bankdata.seed()
    for i in range(30):                                    # far more material than one page holds
        e = bank.add({"section": "projects", "title": f"Side Project {i}", "org": "Python", "confirmed": 1})
        for j in range(3):
            bank.add({"parent_id": e["id"], "confirmed": 1, "tags": ["python"],
                      "text": f"Built component {j} of side project {i} that handles workload {i * 3 + j} correctly"})
    for k in range(4):
        e = bank.add({"section": "experience", "title": f"Contract Role {k}", "org": f"Client {k}", "confirmed": 1})
        for j in range(4):
            bank.add({"parent_id": e["id"], "confirmed": 1,
                      "text": f"Delivered milestone {j} for client {k} and documented release {k * 4 + j}"})
    res = resume.build_detailed()
    assert res.pages == 1 and res.trims
    meta = json.loads(Path(res.path).with_suffix(".json").read_text(encoding="utf-8"))
    kept = [s for s in meta["sections"] if s.startswith("experience:")]
    assert len(kept) == 6                                   # 2 seeded + 4 added: none dropped
    assert resume.verify(res.path) == []
    assert ids["intern"] in "".join(kept)


@needs_browser
def test_role_type_resume_goes_in_its_own_folder_with_a_clean_name(seeded):
    res = resume.build_detailed("hardware")
    p = Path(res.path)
    assert p.name == "Alex_Rivera_Resume.pdf" and p.parent.name == "hardware"
    meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
    assert seeded["ta"] in meta["chosen"]


@needs_browser
def test_posting_variant_adds_company_and_role_and_selects_from_bank_only(seeded):
    posting = {"id": "p1", "company": "Acme Robotics", "title": "Firmware Intern", "field": "hardware",
               "description": "You will write C++ firmware for Arduino based sensors and use Verilog."}
    res = resume.build_detailed(None, posting)
    assert Path(res.path).name == "Alex_Rivera_Resume_Acme_Robotics_Firmware_Intern.pdf"
    assert res.problems == []
    meta = json.loads(Path(res.path).with_suffix(".json").read_text(encoding="utf-8"))
    bank_ids = {b["id"] for e in bank.load(True) for b in e["bullets"]}
    assert {b for ids in meta["chosen"].values() for b in ids} <= bank_ids


def test_verify_resume_lines_setting_turns_the_provenance_check_off(seeded, monkeypatch):
    calls = []
    monkeypatch.setattr(provenance, "verify_pdf", lambda *a, **k: calls.append(1) or ["boom"])
    s = config.load_settings()
    s["apply"]["verify_resume_lines"] = False
    config.save_settings(s)
    res = resume.build_detailed()
    if res.kind == "pdf":
        assert calls == [] and res.problems == []
    s["apply"]["verify_resume_lines"] = True
    config.save_settings(s)
    res = resume.build_detailed()
    if res.kind == "pdf":
        assert calls and res.problems == ["boom"]


def test_without_a_browser_the_html_is_produced_and_the_reason_is_plain(seeded, monkeypatch):
    monkeypatch.setattr(render, "find_browser", lambda: None)
    res = resume.build_detailed()
    assert res.kind == "html" and res.path.endswith(".html") and Path(res.path).exists()
    assert "No Chrome, Edge or Chromium" in res.note and "—" not in res.note
    assert "Alex Rivera" in Path(res.path).read_text(encoding="utf-8")
    assert resume.build() == res.path


def test_no_browser_still_fits_by_estimate(alex, monkeypatch):
    monkeypatch.setattr(render, "find_browser", lambda: None)
    bankdata.seed()
    for i in range(25):
        e = bank.add({"section": "projects", "title": f"P{i}", "confirmed": 1})
        for j in range(3):
            bank.add({"parent_id": e["id"], "confirmed": 1, "text": f"Built part {j} of project {i} with care"})
    res = resume.build_detailed()
    assert res.trims and res.kind == "html"
    chosen = json.loads(Path(res.path).with_suffix(".json").read_text(encoding="utf-8"))["sections"]
    assert sum(1 for s in chosen if s.startswith("experience:")) == 2


def test_empty_bank_and_missing_name_are_plain_errors(tmp_home):
    with pytest.raises(ValueError, match="name"):
        resume.build()
    config.save_profile({"name": {"first": "Alex", "last": "Rivera"}})
    with pytest.raises(resume.BankEmpty, match="no confirmed"):
        resume.build()
    bankdata.seed(confirmed=False)
    with pytest.raises(resume.BankEmpty):
        resume.build()


def test_profile_education_fills_in_when_the_bank_has_none(alex):
    bank.add({"section": "experience", "title": "Tutor", "org": "Self", "confirmed": 1})
    bank.add({"parent_id": "E1", "text": "Tutored 12 students in algebra", "confirmed": 1})
    res = resume.build_detailed()
    html = Path(res.path).read_text(encoding="utf-8") if res.kind == "html" else ""
    if res.kind == "pdf":
        assert "Example University" in render.pdf_text(res.path)
    else:
        assert "Example University" in html


# ------------------------------------------------------------------ resume_for and stale files


@needs_browser
def test_resume_for_follows_tailoring_setting_and_rebuilds_stale_files(seeded):
    s = config.load_settings()
    s["search"]["fields"] = ["software", "hardware"]
    s["apply"]["resume_tailoring"] = "by-role-type"
    posting = {"id": "p1", "company": "Acme", "title": "Dev", "field": "hardware", "description": "C++"}
    hw = resume.resume_for(posting, s)
    assert Path(hw).parent.name == "hardware"
    assert Path(resume.resume_for({**posting, "field": "software"}, s)).parent.name == "software"
    first_mtime = Path(hw).stat().st_mtime_ns
    assert resume.resume_for(posting, s) == hw and Path(hw).stat().st_mtime_ns == first_mtime   # reused

    s["apply"]["resume_tailoring"] = "one"
    one = resume.resume_for(posting, s)
    assert Path(one).name == "Alex_Rivera_Resume.pdf" and Path(one).parent.name == "resumes"
    s["apply"]["resume_tailoring"] = "per-job"
    pj = resume.resume_for(posting, s)
    assert "Acme_Dev" in Path(pj).name

    # editing the bank makes every older file stale; the next request rebuilds it
    files = {f["name"]: f for f in resume.list_files()}
    assert not any(f["stale"] for f in files.values())
    bank.update(seeded["intern"] + ".b1", {"text": "Built a REST API in Python that cut report time by 85 percent"})
    assert all(f["stale"] for f in resume.list_files())
    s["apply"]["resume_tailoring"] = "by-role-type"
    hw2 = resume.resume_for(posting, s)
    assert hw2 == hw and Path(hw).stat().st_mtime_ns != first_mtime
    assert "85 percent" in render.pdf_text(hw) and resume.verify(hw) == []


def test_build_all_makes_one_resume_per_field(seeded, monkeypatch):
    monkeypatch.setattr(render, "find_browser", lambda: None)
    s = config.load_settings()
    s["search"]["fields"] = ["software", "hardware", "data-ml"]
    paths = [r.path for r in resume.build_all(s)]
    assert [Path(p).parent.name for p in paths] == ["software", "hardware", "data-ml"]
    s["apply"]["resume_tailoring"] = "one"
    assert len(resume.build_all(s)) == 1


def test_generated_text_has_no_em_dashes(seeded, monkeypatch):
    monkeypatch.setattr(render, "find_browser", lambda: None)
    res = resume.build_detailed()
    assert "—" not in Path(res.path).read_text(encoding="utf-8")


@needs_browser
def test_our_own_pdf_imports_back_with_sections_entries_and_bullets(seeded, monkeypatch):
    """A resume this tool wrote has no bullet marks in its text layer; the plain parser must still cope."""
    from applyfirst import claude
    res = resume.build_detailed()
    assert res.kind == "pdf"
    originals = {b["text"] for e in bank.load(True) if e["section"] != "skills" for b in e["bullets"]}
    monkeypatch.setattr(claude, "run", lambda *a, **k: claude.Result(False, error="no claude in tests"))
    for r in bank.all_rows():                      # a fresh bank, so nothing is skipped as a duplicate
        if not r["parent_id"]:
            bank.delete(r["id"])
    rows = resume.import_pdf(res.path)
    entries = [r for r in rows if not r["parent_id"]]
    assert {r["section"] for r in entries} >= {"education", "experience", "projects", "skills", "other"}
    got = [r["text"] for r in rows if r["parent_id"]]
    assert len(got) >= 6
    assert all(t in originals or t.startswith("Relevant coursework") for t in got)
    exp = [r for r in entries if r["section"] == "experience"]
    assert any("Software Intern" in r["title"] and "Northwind Labs" in r["org"] for r in exp)
