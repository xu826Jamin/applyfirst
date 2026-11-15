import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applyfirst import store
from applyfirst.apply import api as apply_api
from applyfirst.apply import learn, mark_pending
from test_apply_support import add_posting


@pytest.fixture
def client(tmp_home):
    app = FastAPI()
    app.include_router(apply_api.router, prefix="/api/apply")
    return TestClient(app)


def add_app(pid="g:1", status="queued", company="Acme", title="Intern"):
    return store.execute(
        "INSERT INTO applications (posting_id, company, title, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (pid, company, title, status, store.now(), store.now()))


def add_cost(app_id, cost, mode="review", status="ready-to-submit"):
    store.execute("INSERT INTO application_costs (application_id, run_id, mode, cost_usd, turns, outcome_status, created_at) "
                  "VALUES (?,?,?,?,?,?,?)", (app_id, "r", mode, cost, 5, status, store.now()))


def test_run_spawns_a_job(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(apply_api.jobs, "spawn", lambda kind, fn: captured.update(kind=kind, fn=fn) or "apply-1")
    called = {}
    monkeypatch.setattr(apply_api, "apply_queue", lambda rid, limit: called.update(rid=rid, limit=limit) or "done")
    r = client.post("/api/apply/run", json={"limit": 3})
    assert r.status_code == 200 and r.json() == {"run_id": "apply-1"}
    assert captured["kind"] == "apply"
    assert captured["fn"]("rid9") == "done" and called == {"rid": "rid9", "limit": 3}
    assert client.post("/api/apply/run", json={"limit": "many"}).status_code == 422


def test_run_conflict_when_already_running(client, monkeypatch):
    def boom(kind, fn):
        raise RuntimeError("A apply is already running.")
    monkeypatch.setattr(apply_api.jobs, "spawn", boom)
    assert client.post("/api/apply/run", json={}).status_code == 409


def test_applications_listing_and_filter(client):
    add_posting("g:1")
    a = add_app("g:1", "needs-you")
    add_app("g:2", "submitted")
    add_cost(a, 0.25)
    add_cost(a, 0.5)
    mark_pending(a, "Years of Rust?", "select", ["0", "1-2"])
    rows = client.get("/api/apply/applications").json()
    assert len(rows) == 2
    only = client.get("/api/apply/applications", params={"status": "needs-you"}).json()
    assert len(only) == 1 and only[0]["cost_usd"] == pytest.approx(0.75)
    assert only[0]["questions"][0]["options"] == ["0", "1-2"]
    assert only[0]["posting_url"].startswith("https://")
    both = client.get("/api/apply/applications", params={"status": "needs-you,submitted"}).json()
    assert len(both) == 2


def test_status_change_by_user(client):
    a = add_app(status="ready-to-submit")
    r = client.post(f"/api/apply/applications/{a}/status", json={"status": "submitted"})
    assert r.status_code == 200
    row = r.json()
    assert row["status"] == "submitted" and row["submitted_at"]
    store.execute("UPDATE applications SET status='needs-you', needs_you='captcha' WHERE id=?", (a,))
    row = client.post(f"/api/apply/applications/{a}/status", json={"status": "queued"}).json()
    assert row["status"] == "queued" and row["needs_you"] == ""
    assert client.post(f"/api/apply/applications/{a}/status", json={"status": "bogus"}).status_code == 422
    assert client.post("/api/apply/applications/999/status", json={"status": "failed"}).status_code == 404


def test_answers_pending_and_put(client):
    a = add_app()
    mark_pending(a, "Years of Rust?", "select", ["0", "1-2"])
    learn("Do you know SQL?", "Yes")
    pend = client.get("/api/apply/answers", params={"pending": 1}).json()
    assert len(pend) == 1 and pend[0]["options"] == ["0", "1-2"] and pend[0]["type"] == "select"
    assert pend[0]["application_ids"] == [a]
    assert len(client.get("/api/apply/answers").json()) == 2
    assert len(client.get("/api/apply/answers", params={"pending": 0}).json()) == 1

    r = client.put("/api/apply/answers/years of rust", json={"answer": "1-2"})
    assert r.status_code == 200 and r.json()["pending"] == 0 and r.json()["source"] == "user"
    assert client.get("/api/apply/answers", params={"pending": 1}).json() == []
    assert client.put("/api/apply/answers/years of rust", json={"answer": " "}).status_code == 422
    new = client.put("/api/apply/answers/Shoe size", json={"answer": "10"}).json()
    assert new["key"] == "shoe size" and new["question"] == "Shoe size"


def test_cost_endpoint(client):
    empty = client.get("/api/apply/cost").json()
    assert empty["applications"] == 0 and empty["average_usd"] is None and empty["total_usd"] == 0
    a, b = add_app("g:1", "submitted"), add_app("g:2", "needs-you")
    add_cost(a, 0.4)
    add_cost(a, 0.2)
    add_cost(b, 1.0)
    c = client.get("/api/apply/cost").json()
    assert c["applications"] == 2 and c["runs"] == 3
    assert c["total_usd"] == pytest.approx(1.6)
    assert c["average_usd"] == pytest.approx(0.8)
    assert c["submitted_applications"] == 1 and c["average_per_submitted_usd"] == pytest.approx(0.6)


def test_mounted_in_the_real_server(tmp_home):
    from applyfirst.server import app
    paths = set(app.openapi()["paths"])
    assert "/api/apply/run" in paths and "/api/apply/cost" in paths
