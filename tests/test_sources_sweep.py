"""A whole sweep against a pretend network: what is stored, closed, counted and handed on."""
from datetime import datetime, timedelta, timezone

import pytest
from test_sources_fakes import FakeHttp

from applyfirst import config, store
from applyfirst.sources import boards as boards_mod
from applyfirst.sources import browser, run
from applyfirst.sources.net import FetchError


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


GH = "https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=true"
LONG = ("We are hiring a student developer for a four month work term on our platform team. You will build "
        "services in Python, review designs with senior engineers, test your work and ship to production. " * 2)


def gh_job(id, title, location="Toronto, ON", posted=None, content=LONG):
    return {"id": id, "title": title, "location": {"name": location}, "content": content,
            "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{id}", "first_published": posted or ago(2)}


@pytest.fixture
def world(alex, monkeypatch):
    """Two boards (acme on Greenhouse, nimbus on Greenhouse), fake network, no filters, no browser."""
    state = {"routes": {}, "boards": [
        {"ats": "greenhouse", "token": "acme", "company": "Acme Inc."},
        {"ats": "greenhouse", "token": "nimbus", "company": "Nimbus"}]}
    http = FakeHttp(state["routes"])
    monkeypatch.setattr(run, "Http", lambda *a, **k: http)
    monkeypatch.setattr(boards_mod, "load_all", lambda: state["boards"])
    monkeypatch.setattr(run.boards_mod, "load_all", lambda: state["boards"])
    from applyfirst import filters
    monkeypatch.setattr(filters, "evaluate_all", None, raising=False)
    state["http"] = http
    return state


def set_board(world, token, jobs):
    world["routes"][GH.format(token)] = {"jobs": jobs}


def posting(id):
    return store.one("SELECT * FROM postings WHERE id=?", (id,))


def test_sweep_stores_new_postings_and_reports_plainly(world):
    set_board(world, "acme", [gh_job(1, "Software Engineering Intern"), gh_job(2, "Senior Staff Engineer"),
                              gh_job(3, "Software Intern", location="Austin, TX"),
                              gh_job(4, "Co-op Developer", posted=ago(90))])
    set_board(world, "nimbus", [gh_job(7, "New Grad Software Engineer", location="Remote")])
    summary = run.sweep(store.start_run("sweep"))
    assert summary.startswith("Checked 2 boards, 2 new postings")
    p = posting("greenhouse:acme:1")
    assert p["company"] == "Acme Inc." and p["country"] == "CA" and p["source"] == "greenhouse" and p["ats"] == "greenhouse"
    assert p["alive"] == 1 and p["description"].startswith("We are hiring") and len(p["fingerprint"]) == 16
    assert p["first_seen_at"] >= ago(0)[:10] and p["posted_at"].startswith(ago(2)[:10])
    assert posting("greenhouse:acme:2") is None                  # senior: not what this user asked for
    assert posting("greenhouse:acme:3") is None                  # Texas: not their country
    assert posting("greenhouse:acme:4") is None                  # older than their age limit
    assert posting("greenhouse:nimbus:7")["remote"] == 1
    assert "outside your countries, levels or age limit" in summary


def test_levels_that_a_title_cannot_tell_apart_store_everything_in_the_country(world):
    s = config.load_settings()
    s["search"]["levels"] = ["mid", "senior"]
    config.save_settings(s)
    set_board(world, "acme", [gh_job(2, "Senior Staff Engineer"), gh_job(3, "Software Intern", location="Austin, TX")])
    set_board(world, "nimbus", [])
    run.sweep(store.start_run("sweep"))
    assert posting("greenhouse:acme:2") and posting("greenhouse:acme:3") is None


def test_second_sweep_adds_nothing_and_keeps_what_the_user_did(world):
    set_board(world, "acme", [gh_job(1, "Software Intern")])
    set_board(world, "nimbus", [])
    run.sweep(store.start_run("sweep"))
    store.execute("UPDATE postings SET user_action='approved', verdict='keep' WHERE id='greenhouse:acme:1'")
    summary = run.sweep(store.start_run("sweep"))
    assert "0 new postings" in summary
    p = posting("greenhouse:acme:1")
    assert p["user_action"] == "approved" and p["verdict"] == "keep" and p["alive"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM postings")["n"] == 1


def test_a_posting_that_leaves_a_fully_read_board_is_closed_and_can_come_back(world):
    set_board(world, "acme", [gh_job(1, "Software Intern"), gh_job(2, "Co-op Developer")])
    set_board(world, "nimbus", [gh_job(9, "Intern")])
    run.sweep(store.start_run("sweep"))
    set_board(world, "acme", [gh_job(2, "Co-op Developer")])
    summary = run.sweep(store.start_run("sweep"))
    assert posting("greenhouse:acme:1")["alive"] == 0 and posting("greenhouse:acme:2")["alive"] == 1
    assert posting("greenhouse:nimbus:9")["alive"] == 1             # another board's postings are untouched
    assert "1 posting closed" in summary
    set_board(world, "acme", [gh_job(1, "Software Intern"), gh_job(2, "Co-op Developer")])
    summary = run.sweep(store.start_run("sweep"))
    assert posting("greenhouse:acme:1")["alive"] == 1 and "1 posting reopened" in summary


def test_a_board_that_fails_is_counted_and_nothing_on_it_is_closed(world):
    set_board(world, "acme", [gh_job(1, "Software Intern")])
    set_board(world, "nimbus", [gh_job(9, "Intern")])
    run.sweep(store.start_run("sweep"))
    world["routes"][GH.format("acme")] = FetchError("down", "unreachable")
    del world["routes"][GH.format("nimbus")]                          # 404: the board is gone
    summary = run.sweep(store.start_run("sweep"))
    assert "2 boards could not be read" in summary and "1 gone" in summary and "1 unreachable" in summary
    assert posting("greenhouse:acme:1")["alive"] == 1 and posting("greenhouse:nimbus:9")["alive"] == 1
    st = store.one("SELECT * FROM boards_state WHERE token='acme'")
    assert st["last_status"] == "unreachable" and st["failures"] == 1


def test_a_board_that_suddenly_lists_nothing_is_left_alone(world):
    jobs = [gh_job(i, f"Intern {i}") for i in range(1, 8)]
    set_board(world, "acme", jobs)
    set_board(world, "nimbus", [])
    run.sweep(store.start_run("sweep"))
    set_board(world, "acme", [])
    summary = run.sweep(store.start_run("sweep"))
    assert store.one("SELECT COUNT(*) AS n FROM postings WHERE alive=1")["n"] == 7
    assert "suddenly listed nothing" in summary


def test_an_incomplete_read_never_closes_anything(world, monkeypatch):
    set_board(world, "acme", [gh_job(1, "Software Intern"), gh_job(2, "Co-op Developer")])
    set_board(world, "nimbus", [])
    run.sweep(store.start_run("sweep"))
    from applyfirst.sources import fetchers
    real = fetchers.FETCHERS["greenhouse"]

    def partial(board, ctx):
        r = real(board, ctx)
        r.complete = False
        r.postings = r.postings[:1]
        return r
    monkeypatch.setitem(run.FETCHERS, "greenhouse", partial)
    run.sweep(store.start_run("sweep"))
    assert posting("greenhouse:acme:2")["alive"] == 1


def test_posting_text_missing_from_a_list_is_fetched_for_new_postings_only_and_failures_are_counted(world, monkeypatch):
    sr = "https://api.smartrecruiters.com/v1/companies/{}/postings?limit=100&offset=0"
    world["boards"][:] = [{"ats": "smartrecruiters", "token": "acme", "company": "Acme"}]
    world["routes"][sr.format("acme")] = {"totalFound": 2, "content": [
        {"id": "1", "name": "Software Intern", "location": {"city": "Toronto", "region": "ON", "country": "ca"}},
        {"id": "2", "name": "Co-op Analyst", "location": {"city": "Toronto", "region": "ON", "country": "ca"}}]}
    world["routes"]["https://api.smartrecruiters.com/v1/companies/acme/postings/1"] = {
        "jobAd": {"sections": {"jobDescription": {"text": "<p>Write code for us</p>"}}}}
    world["routes"]["https://api.smartrecruiters.com/v1/companies/acme/postings/2"] = FetchError("boom", "http500", 500)
    summary = run.sweep(store.start_run("sweep"))
    assert posting("smartrecruiters:acme:1")["description"] == "Write code for us"
    assert posting("smartrecruiters:acme:2")["description"] == ""             # not retrieved, never filled in
    assert "Text for 1 posting could not be fetched" in summary


def test_a_closed_posting_found_while_fetching_its_text_is_closed(world):
    sr = "https://api.smartrecruiters.com/v1/companies/{}/postings?limit=100&offset=0"
    world["boards"][:] = [{"ats": "smartrecruiters", "token": "acme", "company": "Acme"}]
    world["routes"][sr.format("acme")] = {"totalFound": 1, "content": [
        {"id": "1", "name": "Software Intern", "location": {"city": "Toronto", "country": "ca"}}]}
    run.sweep(store.start_run("sweep"))                                        # body route missing: 404 = closed
    assert posting("smartrecruiters:acme:1")["alive"] == 0


def test_new_postings_go_to_the_filters_and_matches_are_counted(world, monkeypatch):
    set_board(world, "acme", [gh_job(1, "Software Intern"), gh_job(2, "Co-op Developer")])
    set_board(world, "nimbus", [])
    from applyfirst import filters
    seen = {}

    def evaluate_all(run_id):
        seen["run_id"] = run_id
        store.execute("UPDATE postings SET verdict='keep' WHERE id='greenhouse:acme:1'")
        store.execute("UPDATE postings SET verdict='skip' WHERE id='greenhouse:acme:2'")
    monkeypatch.setattr(filters, "evaluate_all", evaluate_all, raising=False)
    rid = store.start_run("sweep")
    summary = run.sweep(rid)
    assert seen["run_id"] == rid
    assert summary.startswith("Checked 2 boards, 2 new postings, 1 match your settings.")


def test_without_filters_the_postings_are_still_saved_and_it_says_so(world):
    set_board(world, "acme", [gh_job(1, "Software Intern")])
    set_board(world, "nimbus", [])
    summary = run.sweep(store.start_run("sweep"))
    assert summary.startswith("Checked 2 boards, 1 new posting.") and "not filtered yet" in summary
    assert posting("greenhouse:acme:1")


def test_a_filter_crash_does_not_lose_the_postings(world, monkeypatch):
    set_board(world, "acme", [gh_job(1, "Software Intern")])
    set_board(world, "nimbus", [])
    from applyfirst import filters

    def boom(run_id):
        raise RuntimeError("rules file is broken")
    monkeypatch.setattr(filters, "evaluate_all", boom, raising=False)
    summary = run.sweep(store.start_run("sweep"))
    assert posting("greenhouse:acme:1") and "filtering failed" in summary


def test_boards_switched_off_reads_none(world):
    s = config.load_settings()
    s["sources"]["company_boards"] = False
    config.save_settings(s)
    summary = run.sweep(store.start_run("sweep"))
    assert summary.startswith("Checked 0 boards, 0 new postings") and "switched off" in summary
    assert world["http"].calls == []


def test_browser_sources_add_postings_and_the_employer_copy_wins_the_duplicate(world, monkeypatch):
    set_board(world, "acme", [gh_job(1, "Software Intern")])
    set_board(world, "nimbus", [])
    s = config.load_settings()
    s["sources"]["indeed"] = True
    config.save_settings(s)
    rows, _ = browser.normalise_rows("indeed", [
        {"title": "Software Intern", "company": "Acme", "location": "Toronto, ON", "job_key": "k1", "posted": "1d"},
        {"title": "Chef", "company": "Pasta House", "location": "Toronto, ON", "job_key": "k2", "posted": "1d"},
        {"title": "Software Intern", "company": "Elsewhere", "location": "Austin, TX", "job_key": "k3"}], s)
    monkeypatch.setattr(browser, "collect", lambda name, settings, run_id: (rows, "Indeed stopped after 20 searches."))
    summary = run.sweep(store.start_run("sweep"))
    ind = posting("indeed:k1")
    assert ind and ind["duplicate_of"] == "greenhouse:acme:1"
    assert posting("indeed:k2") is None                       # a chef is not an early-career software role
    assert posting("indeed:k3") is None                       # wrong country
    assert posting("greenhouse:acme:1")["duplicate_of"] == ""
    assert "Indeed stopped after 20 searches." in summary


def test_postings_without_a_board_are_checked_at_their_page_a_few_per_sweep(world, monkeypatch):
    set_board(world, "acme", [])
    set_board(world, "nimbus", [])
    old = ago(10)
    for i, page in enumerate(["This job has expired", "Apply for this internship"]):
        store.upsert("postings", {"id": f"indeed:o{i}", "source": "indeed", "company": "Co", "title": "Intern",
                                  "url": f"https://ca.indeed.com/viewjob?jk=o{i}", "first_seen_at": old})
        world["routes"][f"https://ca.indeed.com/viewjob?jk=o{i}"] = page
    run.sweep(store.start_run("sweep"))
    assert posting("indeed:o0")["alive"] == 0 and posting("indeed:o1")["alive"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM liveness_checks")["n"] == 2
    before = len(world["http"].calls)
    run.sweep(store.start_run("sweep"))                       # looked at recently: not looked at again
    assert not [c for c in world["http"].calls[before:] if "indeed" in c[0]]


def test_summary_numbers_are_formatted_for_a_person():
    s = run._summary(4512, 37, 12, run.Counts(), {}, [], {})
    assert s == "Checked 4,512 boards, 37 new postings, 12 match your settings."


def test_search_terms_follow_the_users_levels():
    assert run.search_terms({"search": {"levels": ["internship", "co-op"]}}) == ["intern", "co-op", "coop"]
    assert run.search_terms({"search": {"levels": ["internship", "senior"]}}) == []
    assert run.search_terms({"search": {"levels": []}}) == []


# --------------------------------------------------------------------------------- add by link

def test_add_manual_reads_a_known_system_in_full(alex, monkeypatch):
    http = FakeHttp({GH.format("acme"): {"jobs": [gh_job(55, "Software Intern", location="Waterloo, ON")]}})
    p = run.add_manual("https://boards.greenhouse.io/acme/jobs/55", http=http)
    assert p["id"] == "greenhouse:acme:55" and p["title"] == "Software Intern" and p["country"] == "CA"
    assert p["description"].startswith("We are hiring")
    again = run.add_manual("https://boards.greenhouse.io/acme/jobs/55", http=http)
    assert again["id"] == p["id"] and store.one("SELECT COUNT(*) AS n FROM postings")["n"] == 1


def test_add_manual_stores_an_unknown_link_with_the_page_title(alex):
    http = FakeHttp({"https://careers.example.org/jobs/77": (
        "https://careers.example.org/jobs/77",
        "<html><head><title>Junior Analyst &amp; Co-op - Example Org</title>"
        '<meta property="og:site_name" content="Example Org"></head></html>')})
    p = run.add_manual("https://careers.example.org/jobs/77", http=http)
    assert p["source"] == "manual" and p["company"] == "Example Org"
    assert p["title"] == "Junior Analyst & Co-op - Example Org" and p["description"] == "" and p["alive"] == 1


def test_add_manual_keeps_the_link_when_the_page_cannot_be_opened(alex):
    p = run.add_manual("https://down.example.org/jobs/1", http=FakeHttp({}))
    assert p["url"] == "https://down.example.org/jobs/1" and p["title"] == "https://down.example.org/jobs/1"
    assert p["company"] == "down.example.org"


def test_add_manual_rejects_a_non_link(alex):
    with pytest.raises(ValueError):
        run.add_manual("not a link")


def test_add_manual_when_the_posting_has_left_its_board_still_saves_the_link(alex):
    http = FakeHttp({GH.format("acme"): {"jobs": []},
                     "https://boards.greenhouse.io/acme/jobs/55": ("https://boards.greenhouse.io/acme/jobs/55", "<title>Gone</title>")})
    p = run.add_manual("https://boards.greenhouse.io/acme/jobs/55", http=http)
    assert p["source"] == "manual" and p["ats"] == "greenhouse"


# ----------------------------------------------------------------------------------- the API

def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from applyfirst.sources import api
    app = FastAPI()
    app.include_router(api.router, prefix="/api/sources")
    return TestClient(app), api


def test_api_boards_counts_by_system(tmp_home):
    c, _ = client()
    r = c.get("/api/sources/boards")
    assert r.status_code == 200 and r.json()["greenhouse"] > 50 and "workday" in r.json()


def test_api_sweep_starts_a_job_and_a_second_one_is_refused(tmp_home, monkeypatch):
    c, api = client()
    monkeypatch.setattr(api.jobs, "spawn", lambda kind, fn: "sweep-1")
    assert c.post("/api/sources/sweep").json() == {"run_id": "sweep-1"}

    def busy(kind, fn):
        raise RuntimeError("A sweep is already running.")
    monkeypatch.setattr(api.jobs, "spawn", busy)
    r = c.post("/api/sources/sweep")
    assert r.status_code == 409 and "already running" in r.json()["detail"]


def test_api_manual_returns_the_posting_and_a_bad_link_is_a_422(alex, monkeypatch):
    c, api = client()
    monkeypatch.setattr(api, "add_manual", lambda url: run.add_manual(url, http=FakeHttp(
        {GH.format("acme"): {"jobs": [gh_job(5, "Software Intern")]}})))
    r = c.post("/api/sources/manual", json={"url": "https://boards.greenhouse.io/acme/jobs/5"})
    assert r.status_code == 200 and r.json()["title"] == "Software Intern"
    assert c.post("/api/sources/manual", json={"url": "nonsense"}).status_code == 422
