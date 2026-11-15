"""Pacing, duplicates, closure text, link detection, the board list, browser rows."""
import io
import json
import urllib.error

import pytest

from applyfirst.sources import boards, browser, dedupe, detect, liveness
from applyfirst.sources.net import FetchError, Http, Pacer
from applyfirst.sources.util import company_key, normalise_url, title_variants


# ------------------------------------------------------------------------------------ pacing

def test_pacer_spaces_requests_to_one_host_and_leaves_other_hosts_alone():
    now = [100.0]
    slept = []

    def sleep(s):
        slept.append(round(s, 3))
        now[0] += s
    p = Pacer({"a.example": 0.5}, default=0.5, clock=lambda: now[0], sleep=sleep)
    p.wait("a.example")
    p.wait("a.example")
    p.wait("a.example")
    assert slept == [0.5, 0.5]                      # first is free, the next two wait a gap each
    slept.clear()
    p.wait("b.example")                             # a different host has its own clock
    assert slept == []


def test_shared_api_hosts_get_a_short_gap_and_employer_hosts_a_longer_one():
    p = Pacer()
    assert p.gap_for("boards-api.greenhouse.io") < p.gap_for("acme.wd3.myworkdayjobs.com")
    assert p.gap_for("raw.githubusercontent.com") == 0


class _Resp:
    def __init__(self, body, url="https://x.example/", headers=None):
        self._b, self._u, self.headers = body, url, headers or {}

    def read(self):
        return self._b

    def geturl(self):
        return self._u

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, headers=None):
    return urllib.error.HTTPError("https://x.example/", code, "err", headers or {}, io.BytesIO(b""))


def test_http_retries_a_429_once_then_reports_rate_limited():
    calls = []

    def opener(req, timeout=0):
        calls.append(req.full_url)
        raise _http_error(429, {"Retry-After": "1"})
    h = Http(Pacer({}, default=0, sleep=lambda s: None), opener=opener)
    with pytest.raises(FetchError) as e:
        h.json("https://x.example/a")
    assert e.value.kind == "rate-limited" and len(calls) == 2


def test_http_errors_are_kinds_not_silence():
    def opener404(req, timeout=0):
        raise _http_error(404)

    def opener_down(req, timeout=0):
        raise urllib.error.URLError("no route")
    pace = Pacer({}, default=0, sleep=lambda s: None)
    with pytest.raises(FetchError) as e:
        Http(pace, opener=opener404).json("https://x.example/a")
    assert e.value.kind == "http404" and e.value.status == 404
    with pytest.raises(FetchError) as e:
        Http(pace, opener=opener_down).text("https://x.example/a")
    assert e.value.kind == "unreachable"
    with pytest.raises(FetchError) as e:
        Http(pace, opener=lambda req, timeout=0: _Resp(b"<html>")).json("https://x.example/a")
    assert e.value.kind == "bad-response"


def test_http_reads_json_and_posts_a_payload():
    seen = {}

    def opener(req, timeout=0):
        seen["data"], seen["method"] = req.data, req.get_method()
        return _Resp(b'{"ok": true}')
    h = Http(Pacer({}, default=0), opener=opener)
    assert h.post_json("https://x.example/p", {"a": 1}) == {"ok": True}
    assert json.loads(seen["data"]) == {"a": 1} and seen["method"] == "POST"


# ------------------------------------------------------------------------------- duplicates

def row(id, company="Acme Inc.", title="Software Intern", country="CA", source="greenhouse",
        url="", seen="2026-11-01T00:00:00+00:00", fp="", user_action=""):
    return {"id": id, "company": company, "title": title, "country": country, "source": source,
            "url": url or f"https://x.example/{id}", "first_seen_at": seen, "fingerprint": fp, "user_action": user_action}


def test_company_and_title_normalisation():
    assert company_key("Remarcable, Inc.") == company_key("remarcable") == "remarcable"
    assert company_key("Acme Canada Ltd.") == "acme"
    assert title_variants("Stagiaire en logiciel / Software Developer Intern") >= {"software developer intern"}
    # a hyphen or a term in brackets is a different posting, not a second language
    assert len(title_variants("Engineer - Infrastructure")) == 1
    assert title_variants("Intern (Winter 2027)") != title_variants("Intern (Summer 2027)")
    assert normalise_url("HTTPS://www.Example.com/jobs/1/#top") == "example.com/jobs/1"
    assert normalise_url("https://ca.indeed.com/viewjob?jk=abc") != normalise_url("https://ca.indeed.com/viewjob?jk=def")


def test_same_role_on_two_sites_is_one_posting_and_the_employer_copy_wins():
    rows = [row("indeed:1", source="indeed", url="https://ca.indeed.com/viewjob?jk=1", seen="2026-11-01T00:00:00+00:00"),
            row("greenhouse:acme:9", company="Acme", seen="2026-11-05T00:00:00+00:00")]
    assert dedupe.find_duplicates(rows) == {"indeed:1": "greenhouse:acme:9"}


def test_two_countries_of_one_role_are_two_postings_but_unknown_country_matches():
    assert dedupe.find_duplicates([row("a", country="CA"), row("b", country="US")]) == {}
    d = dedupe.find_duplicates([row("a", country="CA", seen="2026-11-01T00:00:00+00:00"),
                                row("b", country="", seen="2026-11-02T00:00:00+00:00")])
    assert d == {"b": "a"}


def test_a_posting_the_user_acted_on_stays_canonical():
    rows = [row("a", source="greenhouse", seen="2026-11-01T00:00:00+00:00"),
            row("b", source="indeed", seen="2026-11-09T00:00:00+00:00", user_action="approved")]
    assert dedupe.find_duplicates(rows) == {"a": "b"}


TEXT = ("We are hiring a software engineering intern to join our platform team for a four month placement. "
        "You will build and test backend services in Python, work with senior engineers on design reviews, "
        "and ship features to production. Requirements include coursework in data structures and algorithms, "
        "good communication, and curiosity about distributed systems. We offer mentorship and a flexible hybrid schedule.")


def test_fingerprint_near_duplicate_text_matches_and_different_text_does_not():
    a = dedupe.fingerprint_text(TEXT)
    b = dedupe.fingerprint_text(TEXT + " Apply today.")
    c = dedupe.fingerprint_text("Completely different words about pastry baking, sourdough starters and oven temperatures. " * 6)
    assert len(a) == 16 and dedupe.similarity(a, a) == 1.0
    assert dedupe.similarity(a, b) >= dedupe.THRESHOLD > dedupe.similarity(a, c)
    assert dedupe.fingerprint_text("too short") == ""
    assert dedupe.similarity("", a) == 0.0


def test_same_company_same_description_different_title_is_a_duplicate():
    fa, fb = dedupe.fingerprint_text(TEXT), dedupe.fingerprint_text(TEXT + " Apply today.")
    d = dedupe.find_duplicates([row("a", title="Software Intern", fp=fa), row("b", title="SWE Intern - Platform", fp=fb,
                                                                                seen="2026-11-02T00:00:00+00:00")])
    assert d == {"b": "a"}


# --------------------------------------------------------------------------------- liveness

@pytest.mark.parametrize("text,signal", [
    ("Sorry, this job is no longer available.", "expired"),
    ("Cette offre n’est plus disponible.", "expired"),
    ("Diese Stelle ist bereits besetzt.", "expired"),
    ("The position you are trying to apply for has been filled.", "expired"),
    ("Please check the application form has been filled out completely.", None),
    ("Our closed-loop control team is hiring. This role is closed-source friendly.", None),
    ("Just a moment... Enable JavaScript and cookies to continue", "uncertain"),
    ("Software Intern. Apply now. Build great things.", None),
])
def test_body_signal(text, signal):
    assert liveness.body_signal(text)[0] == signal


class _Page:
    def __init__(self, out):
        self.out = out

    def final_url(self, url):
        if isinstance(self.out, Exception):
            raise self.out
        return url, self.out


def test_check_url_never_reads_a_refusal_or_a_wall_as_dead():
    assert liveness.check_url(_Page(FetchError("x", "http404", 404)), "u") == "dead"
    assert liveness.check_url(_Page(FetchError("x", "http410", 410)), "u") == "dead"
    assert liveness.check_url(_Page(FetchError("x", "http403", 403)), "u") == "unknown"
    assert liveness.check_url(_Page(FetchError("x", "rate-limited", 429)), "u") == "unknown"
    assert liveness.check_url(_Page(FetchError("x", "unreachable")), "u") == "unknown"
    assert liveness.check_url(_Page("Just a moment..."), "u") == "unknown"
    assert liveness.check_url(_Page("This job has expired"), "u") == "dead"
    assert liveness.check_url(_Page("Apply for this internship"), "u") == "live"


# ------------------------------------------------------------------------------- link detection

@pytest.mark.parametrize("url,ats,token,job_id", [
    ("https://boards.greenhouse.io/acme/jobs/12345", "greenhouse", "acme", "12345"),
    ("https://job-boards.greenhouse.io/acme/jobs/12345?gh_src=x", "greenhouse", "acme", "12345"),
    ("https://jobs.lever.co/acme/0a1b2c3d-1111-2222-3333-444455556666", "lever", "acme", "0a1b2c3d-1111-2222-3333-444455556666"),
    ("https://jobs.ashbyhq.com/acme/0a1b2c3d-1111-2222-3333-444455556666", "ashby", "acme", "0a1b2c3d-1111-2222-3333-444455556666"),
    ("https://apply.workable.com/acme/j/AB12CD34/", "workable", "acme", "AB12CD34"),
    ("https://jobs.smartrecruiters.com/Acme/743999", "smartrecruiters", "Acme", "743999"),
    ("https://acme.bamboohr.com/careers/7", "bamboohr", "acme", "7"),
])
def test_parse_job_url(url, ats, token, job_id):
    board, jid = detect.parse_job_url(url)
    assert (board["ats"], board["token"], jid) == (ats, token, job_id)


def test_parse_job_url_workday_and_unknowns():
    board, jid = detect.parse_job_url("https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/Toronto/Intern_R1")
    assert board["ats"] == "workday" and board["site"] == "Careers" and jid.endswith("Intern_R1")
    assert detect.parse_job_url("https://example.com/careers/1") is None
    assert detect.parse_job_url("https://boards.greenhouse.io/embed/jobs/1") is None      # an asset path, not a board
    assert detect.vendor_of("https://acme.icims.com/jobs/12/x/job") == "icims"
    assert detect.vendor_of("https://example.com/x") == ""


# ------------------------------------------------------------------------------- board list

def test_user_boards_live_in_the_data_home_not_the_install(tmp_home):
    before = boards.counts()
    assert boards.add_board({"ats": "greenhouse", "token": "brand-new-co", "name": "Brand New"})
    assert not boards.add_board({"ats": "greenhouse", "token": "brand-new-co"})              # already there
    assert not boards.add_board({"ats": "icims", "token": "x"})                                # no reader
    assert not boards.add_board({"ats": "workday", "token": "x"})                              # no site
    assert (tmp_home / "boards.json").exists()
    assert boards.counts()["greenhouse"] == before["greenhouse"] + 1
    seed = json.loads(boards.SEED.read_text(encoding="utf-8"))
    assert all(b["token"] != "brand-new-co" for b in seed)


def test_discover_keeps_only_boards_that_return_postings(tmp_home, monkeypatch):
    from applyfirst import store
    from test_sources_fakes import FakeHttp
    directory = {"companies": [
        {"ats": "greenhouse", "slug": "alive-co", "name": "Alive Co"},
        {"ats": "greenhouse", "slug": "dead-co", "name": "Dead Co"},
        {"ats": "lever", "slug": "empty-co", "name": "Empty Co"},
        {"ats": "icims", "slug": "nope", "name": "No Reader"},
    ]}
    monkeypatch.setattr(boards, "DIRECTORIES", ["https://dir.example/companies.json"])
    http = FakeHttp({
        "https://dir.example/companies.json": directory,
        "https://boards-api.greenhouse.io/v1/boards/alive-co/jobs?content=true": {"jobs": [
            {"id": 1, "title": "Intern", "absolute_url": "https://boards.greenhouse.io/alive-co/jobs/1"}]},
        "https://api.lever.co/v0/postings/empty-co?mode=json": [],
    })
    run_id = store.start_run("discover")
    msg = boards.discover(run_id, http=http)
    kept = boards.load_user()
    assert [b["token"] for b in kept] == ["alive-co"]
    assert msg == "Tried 3 boards, added 1 that have postings, 1 could not be read."


# ------------------------------------------------------------------------------- browser rows

def test_indeed_rows_keep_their_job_key_and_drop_tracking():
    rows = [
        {"title": "Dev Intern", "company": "Acme", "location": "Toronto, ON", "job_key": "abc123", "posted": "2d",
         "url": "https://ca.indeed.com/rc/clk?jk=abc123&fccid=9&vjs=3"},
        {"title": "Dev Intern", "company": "Acme", "location": "Toronto, ON", "job_key": "abc123", "url": ""},     # same posting
        {"title": "Other", "company": "Acme", "job_key": "zzz", "url": ""},
        {"title": "", "company": "Acme", "url": "https://ca.indeed.com/viewjob?jk=q"},                              # no title
    ]
    out, dropped = browser.normalise_rows("indeed", rows, {"search": {"countries": ["CA"]}})
    assert [p["job_id"] for p in out] == ["abc123", "zzz"] and dropped == 1
    assert out[0]["url"] == "https://ca.indeed.com/viewjob?jk=abc123"
    assert out[0]["posted_at"]


def test_other_rows_need_a_real_link_and_lose_tracking_parameters():
    out, dropped = browser.normalise_rows("google_recent", [
        {"title": "Intern", "company": "Acme", "url": "https://jobs.lever.co/acme/0a1b2c3d-1111-2222-3333-444455556666?utm_source=g&lever-source=x"},
        {"title": "Intern 2", "company": "Acme", "url": "not a link"}])
    assert out[0]["url"] == "https://jobs.lever.co/acme/0a1b2c3d-1111-2222-3333-444455556666?lever-source=x" and dropped == 1
    assert out[0]["vendor"] == "lever"
    li, _ = browser.normalise_rows("linkedin", [{"title": "Intern", "company": "Acme",
                                                  "url": "https://www.linkedin.com/jobs/view/software-intern-at-acme-3812345678?trk=x"}])
    assert li[0]["url"] == "https://www.linkedin.com/jobs/view/3812345678/"


SETTINGS = {"search": {"levels": ["internship", "co-op"], "fields": ["software"], "countries": ["CA"], "cities": ["Toronto"],
                       "max_posting_age_days": 30},
            "apply": {"pace_seconds": 4, "browser": "chrome-extension"},
            "sources": {"indeed": True, "glassdoor": False, "linkedin": True, "google_recent": False,
                        "email_alerts": False, "school_board": {"enabled": True, "name": "Career Centre", "url": "https://jobs.school.example"}}}


def test_enabled_sources_and_prompts():
    assert browser.enabled(SETTINGS) == ["indeed", "linkedin", "school_board"]
    assert browser.enabled({"sources": {"school_board": {"enabled": True, "url": ""}}}) == []
    assert browser.search_queries(SETTINGS) == [("software developer intern", "Toronto"), ("software developer co-op", "Toronto")]
    p = browser.build_prompt("indeed", SETTINGS)
    assert "ca.indeed.com" in p and "sort=date" in p and "4 seconds" in p and "jobkey" in p
    assert "never click Apply" in p and "STOP that search" in p                  # a 429 ends the search, never routed around
    assert "Easy Apply" in browser.build_prompt("linkedin", SETTINGS)
    assert "jobs.school.example" in browser.build_prompt("school_board", SETTINGS)
    assert "—" not in p                                                       # no em dashes in generated text
    with pytest.raises(ValueError):
        browser.build_prompt("nope", SETTINGS)


def test_collect_skips_politely_without_claude(monkeypatch):
    monkeypatch.setattr(browser.claude, "available", lambda: False)
    rows, note = browser.collect("indeed", SETTINGS, "run")
    assert rows == [] and "not installed" in note


def test_collect_returns_rows_and_the_reason_a_search_stopped(monkeypatch):
    class R:
        ok = True
        error = ""
        structured = {"rows": [{"title": "Intern", "company": "Acme", "job_key": "k1", "location": "Toronto, ON"}],
                      "stopped": "Indeed showed a too-many-requests page after 20 searches."}
    monkeypatch.setattr(browser.claude, "available", lambda: True)
    monkeypatch.setattr(browser.claude, "run", lambda *a, **k: R())
    rows, note = browser.collect("indeed", SETTINGS, "run")
    assert len(rows) == 1 and "too-many-requests" in note
