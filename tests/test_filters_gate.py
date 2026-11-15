"""Filters: evaluate() keeps or skips one posting, and says why in plain language."""
import copy
import datetime as dt

import pytest

from applyfirst import config
from applyfirst.filters import evaluate

NOW = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.timezone.utc)


def posting(**kw):
    p = {"id": "greenhouse:1", "source": "greenhouse", "company": "Acme Robotics",
         "title": "Software Engineer Intern", "location": "Toronto, ON", "remote": 0, "country": "",
         "description": "Build software with our team. A 4 month internship.",
         "posted_at": "2026-11-10T09:00:00Z", "first_seen_at": "2026-11-10T10:00:00Z",
         "deadline": "", "level": "", "field": "", "term_months": None, "duplicate_of": "",
         "alive": 1, "raw": "{}"}
    p.update(kw)
    return p


@pytest.fixture
def env(alex):
    return config.load_settings(), config.load_profile()


def run(env, p=None, applied=None, **search):
    settings, profile = copy.deepcopy(env[0]), env[1]     # each call starts from the same settings
    settings["search"].update(search)
    return evaluate(p if p is not None else posting(), settings, profile, now=NOW, applied=applied)


def test_a_matching_posting_is_kept_with_reasons(env):
    verdict, reasons = run(env)
    assert verdict == "keep"
    assert any("level" in r.lower() for r in reasons)
    assert any("software" in r.lower() for r in reasons)
    assert any("Toronto" in r for r in reasons)
    assert "Posted 5 days ago" in reasons


def test_skip_lists_every_reason(env):
    verdict, reasons = run(env, posting(title="Senior Sales Manager", location="Calgary, AB"))
    assert verdict == "skip"
    assert len(reasons) >= 3
    assert "Outside your locations: Calgary, AB" in reasons


def test_level(env):
    assert run(env, posting(title="Senior Software Engineer"))[0] == "skip"
    assert run(env, posting(title="Software Engineer Co-op"))[0] == "keep"
    # no signal at all: skipped for a student-only setting, kept once entry roles are wanted
    unmarked = posting(title="Software Engineer", description="Build things.")
    v, reasons = run(env, unmarked)
    assert v == "skip" and "internship, co-op or new-grad" in reasons[0]
    assert run(env, unmarked, levels=["internship", "entry"])[0] == "keep"
    assert run(env, posting(title="Senior Software Engineer"), levels=[])[0] == "keep"   # no choice: any level


def test_field(env):
    assert run(env, posting(title="Marketing Intern"))[0] == "skip"
    assert run(env, posting(title="Marketing Intern"), fields=["marketing"])[0] == "keep"
    assert run(env, posting(title="Software Engineer, Financial Crimes Platform Intern"))[0] == "keep"
    assert run(env, posting(title="Delivery Driver Apprentice"))[0] == "skip"
    assert run(env, posting(title="Sales Engineer Intern"))[0] == "skip"


def test_unknown_field_is_not_a_mismatch(env):
    assert run(env, posting(title="Summer Intern", description=""))[0] == "keep"


def test_location(env):
    assert run(env, posting(location="Calgary, AB"))[0] == "skip"
    assert run(env, posting(location="Remote - US"))[0] == "skip"
    assert run(env, posting(location="Remote - US"), countries=[], regions=[])[0] == "keep"
    assert run(env, posting(location="Remote"), remote="exclude")[0] == "skip"


def test_posting_age(env):
    old = posting(posted_at="2026-09-01T00:00:00Z")
    v, reasons = run(env, old)
    assert v == "skip" and any("limit is 30 days" in r for r in reasons)
    assert run(env, old, max_posting_age_days=0)[0] == "keep"           # 0 means no limit
    # no posted date: the first-seen date stands in
    assert run(env, posting(posted_at=""))[0] == "keep"
    assert run(env, posting(posted_at="", first_seen_at="2026-01-01T00:00:00Z"))[0] == "skip"
    assert run(env, posting(posted_at="not a date", first_seen_at=""))[0] == "keep"


def test_start_terms(env):
    assert run(env, posting(title="Software Intern Summer 2027"), start_terms=["2027-05"])[0] == "keep"
    v, reasons = run(env, posting(title="Software Intern Fall 2027"), start_terms=["2027-05"])
    assert v == "skip" and "Fall 2027" in reasons[0]
    assert run(env, posting(), start_terms=["2027-05"])[0] == "keep"       # none stated: kept


def test_minimum_term_length(env):
    assert run(env, posting(description="A 4 month internship."), min_term_months=8)[0] == "skip"
    assert run(env, posting(description="A 12-16 month internship."), min_term_months=8)[0] == "keep"
    assert run(env, posting(description="An internship."), min_term_months=8)[0] == "keep"
    assert run(env, posting(description="Not a 3 months of experience job."), min_term_months=8)[0] == "keep"


def test_language(env):
    s = {"skip_language_required": ["French"]}
    assert run(env, posting(description="French is required."), **s)[0] == "skip"
    assert run(env, posting(description="French is an asset."), **s)[0] == "keep"
    assert run(env, posting(title="Bilingual Software Intern"), **s)[0] == "skip"
    assert run(env, posting(description="French is required."))[0] == "keep"   # not on the user's list


def test_keywords(env):
    assert run(env, include_keywords=["Python"])[0] == "skip"
    assert run(env, posting(description="We use Python daily. " * 3), include_keywords=["python"])[0] == "keep"
    assert run(env, posting(description="We use JavaScript " * 3), include_keywords=["java"])[0] == "skip"   # whole words
    assert run(env, exclude_keywords=["robotics"])[0] == "keep"          # company name is not searched
    assert run(env, posting(description="Unpaid placement. " * 3), exclude_keywords=["unpaid"])[0] == "skip"
    v, reasons = run(env, posting(description=""), include_keywords=["rust"])
    assert v == "keep" and any("not checked" in r for r in reasons)      # no body yet: unknown, not a miss


def test_excluded_company(env):
    assert run(env, exclude_companies=["acme robotics"])[0] == "skip"
    assert run(env, exclude_companies=["Acme Robotics Inc."])[0] == "skip"
    assert run(env, exclude_companies=["Other Co"])[0] == "keep"


def test_closed_duplicate_dead(env):
    assert run(env, posting(alive=0))[0] == "skip"
    assert run(env, posting(duplicate_of="lever:9"))[0] == "skip"
    assert run(env, posting(description="This position is no longer accepting applications."))[0] == "skip"
    v, reasons = run(env, posting(deadline="2026-10-01"))
    assert v == "skip" and "2026-10-01" in reasons[0]
    assert run(env, posting(deadline="2027-01-01"))[0] == "keep"
    # a deadline written in the text with its year counts; a yearless one never closes a posting
    assert run(env, posting(description="Deadline: 2026-09-30. A 4 month internship."))[0] == "skip"
    assert run(env, posting(description="Apply by Feb 10."))[0] == "keep"


def test_us_citizenship_and_sponsorship(env):
    us = posting(location="Remote - US", description="You must be a US citizen.")
    assert run(env, us, countries=[], regions=[])[0] == "skip"
    note = run(env, posting(description="Requires an active TS/SCI clearance."), countries=[], regions=[])
    assert note[0] == "skip"
    # unable to sponsor, and the user needs sponsorship for the posting's country
    no = posting(location="San Francisco, CA", description="We cannot provide visa sponsorship.")
    v, reasons = run(env, no, countries=[], regions=[])
    assert v == "skip" and any("sponsorship" in r for r in reasons)
    # in Canada the user is authorized: the same sentence does not matter
    assert run(env, posting(description="We cannot provide visa sponsorship."))[0] == "keep"


def test_citizenship_unknown_is_a_note_not_a_skip(alex):
    settings = config.load_settings()
    profile = config.load_profile()
    profile["citizenship"] = []
    v, reasons = evaluate(posting(description="Must be a US citizen."), settings, profile, now=NOW)
    assert v == "keep" and any("citizenship" in r.lower() for r in reasons)


def test_school_note_only(env):
    p = posting(description="Open to students enrolled at the University of Waterloo. Python work.")
    v, reasons = run(env, p)
    assert v == "keep" and any("Waterloo" in r for r in reasons)


def test_already_applied(env):
    mine = [{"posting_id": "greenhouse:1", "company": "Acme Robotics", "title": "Software Engineer Intern",
             "status": "submitted", "location": "Toronto, ON"}]
    v, reasons = run(env, posting(), applied=mine)
    assert v == "skip" and reasons == ["You already applied to this"]
    # the same role posted on another board, same city
    again = posting(id="lever:7", company="Acme Robotics Inc.")
    assert run(env, again, applied=mine)[0] == "skip"
    # a different city is a different requisition
    other = posting(id="lever:8", location="Ottawa, ON")
    assert run(env, other, applied=mine)[0] == "keep"
    # the posting's own queued application is not a reason to skip it
    queued = [{**mine[0], "status": "queued"}]
    assert run(env, posting(), applied=queued)[0] == "keep"
    failed = [{**mine[0], "posting_id": "x", "status": "failed"}]
    assert run(env, posting(id="lever:7"), applied=failed)[0] == "keep"


def test_reasons_are_plain_text(env):
    cases = [posting(title="Senior Sales Manager", location="Calgary, AB", description="French is required"),
             posting(), posting(alive=0), posting(deadline="2020-01-01")]
    for p in cases:
        _, reasons = run(env, p, skip_language_required=["French"], include_keywords=["zzz"])
        assert reasons
        for r in reasons:
            assert "—" not in r and "–" not in r        # no em or en dashes
            assert "  " not in r and r == r.strip()
            assert not r.startswith("{") and "None" not in r


def test_evaluate_never_raises_on_odd_postings(env):
    for p in ({}, {"title": None, "description": None}, {"title": "Intern", "raw": "{not json"},
              {"title": "Intern", "posted_at": 5, "term_months": "x"}):
        verdict, reasons = run(env, p)
        assert verdict in ("keep", "skip") and reasons
