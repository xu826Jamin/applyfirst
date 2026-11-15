"""New-match alerts: who gets told, with what, and that a failure never breaks a sweep."""
from applyfirst import alerts, config, store


def _post(pid, verdict="keep", seen="2026-11-15T10:00:00+00:00"):
    store.upsert("postings", {"id": pid, "source": "greenhouse", "company": "Acme", "title": f"Intern {pid}",
                              "location": "Toronto, ON", "url": f"https://example.com/{pid}",
                              "first_seen_at": seen, "verdict": verdict})


def test_only_new_kept_postings_count(tmp_home):
    _post("old", seen="2026-11-01T00:00:00+00:00")
    _post("new1")
    _post("new2")
    _post("skipped", verdict="skip")
    rows = alerts.new_matches_since("2026-11-15T00:00:00+00:00")
    assert sorted(r["title"] for r in rows) == ["Intern new1", "Intern new2"]
    title, body = alerts.message(rows)
    assert title == "2 new matches on applyfirst" and "Acme" in body


def test_desktop_alert_sent_and_logged(tmp_home, monkeypatch):
    _post("a")
    sent = []
    monkeypatch.setattr(alerts, "desktop", lambda t, b: sent.append((t, b)) or "")
    rid = store.start_run("sweep")
    note = alerts.after_sweep(rid, "2026-11-15T00:00:00+00:00")
    assert sent and sent[0][0] == "1 new match on applyfirst"
    assert note == ""


def test_min_new_and_off_switch(tmp_home, monkeypatch):
    _post("a")
    sent = []
    monkeypatch.setattr(alerts, "desktop", lambda t, b: sent.append(t) or "")
    s = config.load_settings()
    s["alerts"]["min_new"] = 2
    config.save_settings(s)
    alerts.after_sweep(store.start_run("sweep"), "2026-11-15T00:00:00+00:00")
    s["alerts"].update({"min_new": 1, "desktop": False, "email": False})
    config.save_settings(s)
    alerts.after_sweep(store.start_run("sweep"), "2026-11-15T00:00:00+00:00")
    assert sent == []


def test_email_needs_settings_and_reports_why(tmp_home):
    err = alerts.email_self("t", [], config.load_settings())
    assert "not set up" in err


def test_smtp_host_from_imap():
    assert alerts.smtp_host("imap.gmail.com") == "smtp.gmail.com"
    assert alerts.smtp_host("imap.gmail.com", "smtp.example.com") == "smtp.example.com"


def test_failed_desktop_alert_is_reported_not_raised(tmp_home, monkeypatch):
    _post("a")
    monkeypatch.setattr(alerts, "desktop", lambda t, b: "no notification tool")
    note = alerts.after_sweep(store.start_run("sweep"), "2026-11-15T00:00:00+00:00")
    assert "Desktop alert failed" in note
