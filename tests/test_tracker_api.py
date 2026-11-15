"""tracker routes, through the real app."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from applyfirst import store
from applyfirst.tracker import imapmail
from applyfirst.server import app as server_app

import test_tracker_helpers as H
from test_tracker_helpers import add_app, app, raw_mail


@pytest.fixture
def client(tmp_home):
    return TestClient(server_app)


def test_outcome_route(client):
    a = add_app("Brightwave", "Software Intern", status="ready-to-submit")
    r = client.post(f"/api/tracker/applications/{a}/outcome", json={"outcome": "interview"})
    assert r.status_code == 200 and r.json()["outcome"] == "interview"
    assert app(a)["status"] == "submitted"
    assert client.post(f"/api/tracker/applications/{a}/outcome", json={"outcome": "nope"}).status_code == 400
    assert client.post("/api/tracker/applications/9999/outcome", json={"outcome": "offer"}).status_code == 404


def test_stats_route(client):
    add_app("Brightwave", "Software Intern", outcome="interview")
    r = client.get("/api/tracker/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["applications"] == 1 and body["totals"]["note"] == "too few to compare"


def test_sync_route_starts_a_run_and_says_plainly_when_email_is_off(client):
    r = client.post("/api/tracker/sync")
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    for _ in range(100):
        run = store.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if run["status"] != "running":
            break
        time.sleep(0.05)
    assert run["status"] == "done" and "not set up" in run["summary"].lower()


def test_messages_and_match_routes(client, monkeypatch):
    H.configure_mail()
    a = add_app("Brightwave", "Embedded Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    b = add_app("Brightwave", "Data Analyst Intern", submitted_at="2026-11-02T10:00:00+00:00")
    held = [raw_mail("jobs@brightwave-hr.example", "Brightwave: your application",
                     "Unfortunately we are not moving forward with your application at "
                     "Brightwave.", "2026-11-09T14:00:00", "amb1"),
            raw_mail("jobs@kestrel-hr.example", "Kestrel interview", "Schedule an interview "
                     "for the internship at Kestrel.", "2026-11-09T15:00:00", "other1")]
    monkeypatch.setattr(imapmail, "connect", lambda *a_, **k: H.StubIMAP(held))
    from applyfirst.tracker import syncer
    rid = store.start_run("sync")
    syncer.sync(rid)

    allm = client.get("/api/tracker/messages").json()
    assert len(allm) == 1                          # the unknown-employer mail is not kept
    unm = client.get("/api/tracker/messages?unmatched=1").json()
    assert len(unm) == 1 and unm[0]["subject"] == "Brightwave: your application"
    assert {c["id"] for c in unm[0]["candidates"]} == {a, b}
    mid = unm[0]["id"]
    assert client.post(f"/api/tracker/messages/{mid}/match", json={"application_id": 9999}).status_code == 404
    assert client.post("/api/tracker/messages/9999/match", json={"application_id": a}).status_code == 404
    r = client.post(f"/api/tracker/messages/{mid}/match", json={"application_id": a})
    assert r.status_code == 200 and r.json()["message"]["application_id"] == a
    assert app(a)["outcome"] == "rejected" and app(b)["outcome"] == ""
    assert client.get("/api/tracker/messages?unmatched=1").json() == []
