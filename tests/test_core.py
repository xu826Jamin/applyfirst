from fastapi.testclient import TestClient

from applyfirst import config, jobs, store


def test_settings_merge_keeps_new_defaults(tmp_home):
    config.save_settings({"queue": {"order_by": "deadline"}})
    s = config.load_settings()
    assert s["queue"]["order_by"] == "deadline"
    assert s["queue"]["daily_limit"] == config.DEFAULT_SETTINGS["queue"]["daily_limit"]
    assert s["apply"]["mode"] == "review"


def test_failed_job_is_recorded_not_swallowed(tmp_home):
    def boom(run_id):
        raise ValueError("bad thing")

    rid, summary, ok = jobs.run_now("sweep", boom)
    assert not ok
    row = store.one("SELECT * FROM runs WHERE id=?", (rid,))
    assert row["status"] == "failed" and "bad thing" in row["summary"]


def test_api_profile_and_status(tmp_home):
    from applyfirst.server import app

    c = TestClient(app)
    assert c.get("/api/status").json()["set_up"] is False
    c.put("/api/profile", json={"name": {"first": "Alex"}, "email": "a@example.com"})
    assert c.get("/api/status").json()["set_up"] is True
    assert c.get("/api/profile").json()["name"]["last"] == ""


def test_secret_values_never_returned(tmp_home):
    from applyfirst.server import app

    c = TestClient(app)
    c.put("/api/secrets/imap_password", json={"value": "hunter2"})
    body = c.get("/api/secrets").json()
    assert body == {"imap_password": True}
