"""Filters: ordering, the queue views, evaluate_all and the HTTP routes."""
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from applyfirst import config, filters, store
from applyfirst.filters import ordering as order_mod

TODAY = dt.date(2026, 11, 15)


def row(pid, **kw):
    base = {"id": pid, "source": "greenhouse", "company": "Acme", "title": "Software Engineer Intern",
            "location": "Toronto, ON", "url": f"https://example.com/{pid}",
            "description": "Build software in a 4 month internship.",
            "posted_at": "", "first_seen_at": "2026-11-14T10:00:00Z", "deadline": ""}
    base.update(kw)
    return base


def put(*rows):
    for r in rows:
        store.upsert("postings", r)


def settings(order_by="newest", then_by="deadline"):
    s = config.load_settings()
    s["queue"]["order_by"] = order_by
    s["queue"]["then_by"] = then_by
    return s


def ids(items):
    return [p["id"] for p in items]


# ------------------------------------------------------------------ order()


def test_order_newest():
    ps = [row("a", posted_at="2026-11-01T00:00:00Z"), row("b", posted_at="2026-11-12T00:00:00Z"),
          row("c", posted_at="", first_seen_at="2026-11-14T00:00:00Z"), row("d", posted_at="junk", first_seen_at="")]
    assert ids(filters.order(ps, settings("newest"))) == ["c", "b", "a", "d"]      # unreadable dates last


def test_order_deadline_upcoming_first_past_and_none_after():
    ps = [row("none"), row("past", deadline="2026-11-01"), row("late", deadline="2027-03-01"),
          row("soon", deadline="2026-11-20")]
    got = order_mod.order(ps, settings("deadline", "company"), today=TODAY)
    assert ids(got)[:2] == ["soon", "late"]
    assert set(ids(got)[2:]) == {"none", "past"}          # a past date is never "soonest"


def test_order_company_then_newest():
    ps = [row("a", company="zeta", posted_at="2026-11-01T00:00:00Z"),
          row("b", company="Acme", posted_at="2026-11-01T00:00:00Z"),
          row("c", company="acme", posted_at="2026-11-09T00:00:00Z")]
    assert ids(filters.order(ps, settings("company", "newest"))) == ["c", "b", "a"]


def test_order_is_repeatable_on_ties():
    ps = [row(f"p{i}", company="Same", title="Same") for i in (3, 1, 2)]
    first = ids(filters.order(ps, settings("company", "deadline")))
    assert first == ["p1", "p2", "p3"]
    assert ids(filters.order(list(reversed(ps)), settings("company", "deadline"))) == first


def test_invalid_order_keys_fall_back():
    ps = [row("a", posted_at="2026-11-01T00:00:00Z"), row("b", posted_at="2026-11-12T00:00:00Z")]
    s = settings("nonsense", "alsonot")
    assert ids(filters.order(ps, s)) == ["b", "a"]


def test_order_does_not_change_its_input():
    ps = [row("a", posted_at="2026-11-01T00:00:00Z"), row("b", posted_at="2026-11-12T00:00:00Z")]
    filters.order(ps, settings())
    assert ids(ps) == ["a", "b"]


def test_order_match_uses_confirmed_experience(tmp_home):
    exp = [{"id": 1, "section": "projects", "title": "Robot", "org": "", "dates": "", "confirmed": 1,
            "text": "Built a robot arm controller in Python and C++ on Linux.", "tags": json.dumps(["python"])},
           {"id": 2, "section": "projects", "title": "Draft", "org": "", "dates": "", "confirmed": 0,
            "text": "Kubernetes terraform aws", "tags": "[]"}]
    ps = [row("none", description="Sell insurance to people."),
          row("some", description="You know Python and Linux."),
          row("draft", description="Kubernetes, terraform and aws.")]
    got = order_mod.order(ps, settings("match", "company"), today=TODAY, experience=exp)
    assert ids(got)[0] == "some"                   # the unconfirmed row does not count
    terms, tags = order_mod.experience_profile(exp)
    assert "kubernetes" not in terms
    m = order_mod.rough_match(ps[1], terms, tags)
    assert m["shared"] == 2 and m["asked"] == 2


def test_vocabulary_has_no_function_words():
    for word in ("the", "and", "to", "in", "with", "or", "is", "team", "strong"):
        assert not order_mod.vocab_in(f"We want {word} people")


# ------------------------------------------------------------------ evaluate_all and the queue


@pytest.fixture
def stocked(alex):
    put(row("keep1", posted_at="2026-11-13T00:00:00Z"),
        row("keep2", company="Beta", title="Software Developer Co-op", posted_at="2026-11-14T00:00:00Z"),
        row("far", title="Software Engineer Intern", location="Calgary, AB"),
        row("senior", title="Senior Software Engineer"),
        row("dead", alive=0),
        row("dup", duplicate_of="keep1"))
    return alex


def test_evaluate_all_writes_verdicts_and_returns_counts(stocked):
    result = filters.evaluate_all()
    assert result["total"] == 4                      # dead and duplicate rows are not evaluated
    assert result["kept"] == 2 and result["skipped"] == 2 and result["new_kept"] == 2
    assert result["by_reason"]["location"] == 1 and result["by_reason"]["level"] == 1
    assert "2 of 4" in result["summary"]
    r = store.one("SELECT * FROM postings WHERE id='far'")
    assert r["verdict"] == "skip" and "Outside your locations: Calgary, AB" in json.loads(r["verdict_reasons"])
    k = store.one("SELECT * FROM postings WHERE id='keep2'")
    assert k["verdict"] == "keep" and k["level"] == "co-op" and k["field"] == "software"
    assert k["term_months"] == 4 and k["country"] == "CA"
    assert store.one("SELECT verdict FROM postings WHERE id='dead'")["verdict"] == ""
    assert store.one("SELECT verdict FROM postings WHERE id='dup'")["verdict"] == ""


def test_evaluate_all_new_kept_counts_only_changes(stocked):
    filters.evaluate_all()
    assert filters.evaluate_all()["new_kept"] == 0
    put(row("fresh", company="Gamma"))
    r = filters.evaluate_all()
    assert r["new_kept"] == 1 and r["kept"] == 3


def test_evaluate_all_follows_changed_settings(stocked):
    filters.evaluate_all()
    s = config.load_settings()
    s["search"]["regions"] = ["Alberta"]
    s["search"]["countries"] = ["CA"]
    config.save_settings(s)
    result = filters.evaluate_all()
    assert result["kept"] == 1
    assert store.one("SELECT verdict FROM postings WHERE id='far'")["verdict"] == "keep"


def test_evaluate_all_logs_to_the_run(stocked):
    run_id = store.start_run("filter")
    filters.evaluate_all(run_id)
    log = open(store.one("SELECT log_file FROM runs WHERE id=?", (run_id,))["log_file"], encoding="utf-8").read()
    assert "match your settings" in log


def test_evaluate_all_skips_what_is_already_applied(stocked):
    store.upsert("applications", {"posting_id": "keep1", "company": "Acme", "title": "Software Engineer Intern",
                                  "status": "submitted", "created_at": store.now(), "updated_at": store.now()},
                 key="id")
    filters.evaluate_all()
    r = store.one("SELECT verdict, verdict_reasons FROM postings WHERE id='keep1'")
    assert r["verdict"] == "skip" and "already applied" in r["verdict_reasons"]


def test_queue_views(stocked):
    filters.evaluate_all()
    s = settings()
    assert ids(filters.queue(s, "kept")) == ["keep2", "keep1"]          # newest first
    store.execute("UPDATE postings SET user_action='approved' WHERE id='keep1'")
    store.execute("UPDATE postings SET user_action='skipped' WHERE id='keep2'")
    assert ids(filters.queue(s, "kept")) == []
    assert ids(filters.queue(s, "approved")) == ["keep1"]
    assert set(ids(filters.queue(s, "skipped"))) == {"keep2", "far", "senior"}
    assert len(filters.queue(s, "all")) == 4                            # live, non-duplicate only


def test_queue_limit_and_rows(stocked):
    filters.evaluate_all()
    got = filters.queue(settings(), "kept", limit=1)
    assert len(got) == 1
    p = got[0]
    assert p["description"] and p["apply_url"] is not None             # full row, for the apply package
    assert isinstance(p["reasons"], list) and p["reasons"]
    assert set(p["rough_match"]) == {"shared", "asked", "terms"}


def test_queue_rejects_unknown_view(stocked):
    with pytest.raises(ValueError):
        filters.queue(settings(), "bogus")


# ------------------------------------------------------------------ HTTP


@pytest.fixture
def client(stocked):
    from applyfirst.server import app
    filters.evaluate_all()
    with TestClient(app) as c:
        yield c


def test_api_queue(client):
    r = client.get("/api/filters/queue")
    assert r.status_code == 200
    body = r.json()
    assert body["view"] == "kept" and body["total"] == 2
    assert body["counts"] == {"kept": 2, "approved": 0, "skipped": 2, "all": 4}
    first = body["postings"][0]
    assert first["id"] == "keep2" and "description" not in first and "raw" not in first
    assert first["snippet"] and first["reasons"]
    assert len(client.get("/api/filters/queue?view=all&limit=2").json()["postings"]) == 2
    assert client.get("/api/filters/queue?view=nope").status_code == 422


def test_api_action_and_reset(client):
    r = client.post("/api/filters/postings/keep1/action", json={"action": "approve"})
    assert r.status_code == 200 and r.json()["user_action"] == "approved"
    assert [p["id"] for p in client.get("/api/filters/queue?view=approved").json()["postings"]] == ["keep1"]
    assert [p["id"] for p in client.get("/api/filters/queue").json()["postings"]] == ["keep2"]
    assert client.post("/api/filters/postings/keep1/action", json={"action": "skip"}).json()["user_action"] == "skipped"
    assert client.post("/api/filters/postings/keep1/action", json={"action": "reset"}).json()["user_action"] == ""
    assert client.post("/api/filters/postings/keep1/action", json={"action": "explode"}).status_code == 422
    assert client.post("/api/filters/postings/nope/action", json={"action": "approve"}).status_code == 404


def test_api_ids_with_colons_and_slashes(client):
    put(row("workday:acme/job/Toronto_R-1"))
    r = client.post("/api/filters/postings/workday:acme/job/Toronto_R-1/action", json={"action": "approve"})
    assert r.status_code == 200
    assert client.get("/api/filters/postings/workday:acme/job/Toronto_R-1").json()["user_action"] == "approved"


def test_api_get_posting_has_reasons(client):
    r = client.get("/api/filters/postings/far")
    assert r.status_code == 200
    body = r.json()
    assert body["reasons"] == ["Outside your locations: Calgary, AB"] or \
        "Outside your locations: Calgary, AB" in body["reasons"]
    assert "raw" not in body and body["description"]
    assert client.get("/api/filters/postings/missing").status_code == 404


def test_api_reevaluate(client):
    s = config.load_settings()
    s["search"]["levels"] = ["senior"]
    config.save_settings(s)
    r = client.post("/api/filters/reevaluate")
    assert r.status_code == 200
    body = r.json()
    assert body["kept"] == 1 and body["run_id"] and "match your settings" in body["summary"]
    assert [p["id"] for p in client.get("/api/filters/queue").json()["postings"]] == ["senior"]
