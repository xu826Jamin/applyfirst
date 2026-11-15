"""The in-app scheduler: daily run at its time, a search every sweep_interval_hours, replies every
sync_interval_hours. Also the alert email's choice of connection by port."""
from datetime import datetime, timedelta, timezone

from applyfirst import alerts, config, daily, jobs, store


def _spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "running", lambda: [])
    monkeypatch.setattr(jobs, "spawn", lambda kind, fn: calls.append(kind) or kind)
    return calls


def _ran(kind, hours_ago):
    rid = store.start_run(kind)
    when = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    store.execute("UPDATE runs SET started_at=? WHERE id=?", (when, rid))


def test_no_interval_search_before_the_first_one(alex, monkeypatch):
    calls = _spawned(monkeypatch)
    assert daily.tick() is None and calls == []


def test_search_reruns_after_interval(alex, monkeypatch):
    calls = _spawned(monkeypatch)
    _ran("sweep", 7)
    assert daily.tick() == "sweep"


def test_search_waits_inside_interval(alex, monkeypatch):
    calls = _spawned(monkeypatch)
    _ran("sweep", 2)
    assert daily.tick() is None and calls == []


def test_zero_interval_turns_it_off(alex, monkeypatch):
    calls = _spawned(monkeypatch)
    s = config.load_settings()
    s["sources"]["sweep_interval_hours"] = 0
    config.save_settings(s)
    _ran("sweep", 100)
    assert daily.tick() is None


def test_sync_runs_on_its_interval_when_email_on(alex, monkeypatch):
    calls = _spawned(monkeypatch)
    s = config.load_settings()
    s["tracker"]["email"]["enabled"] = True
    config.save_settings(s)
    _ran("sweep", 1)
    _ran("sync", 30)
    assert daily.tick() == "sync"


def test_nothing_starts_while_a_search_runs(alex, monkeypatch):
    monkeypatch.setattr(jobs, "running", lambda: ["sweep"])
    monkeypatch.setattr(jobs, "spawn", lambda kind, fn: (_ for _ in ()).throw(AssertionError("spawned")))
    _ran("sweep", 50)
    assert daily.tick() is None


class _FakeSMTP:
    used = []

    def __init__(self, host, port, **kw):
        self.kind = type(self).__name__
        _FakeSMTP.used.append((self.kind, port))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        _FakeSMTP.used.append(("starttls", None))

    def login(self, u, p):
        pass

    def send_message(self, m):
        pass


class SMTP(_FakeSMTP):
    pass


class SMTP_SSL(_FakeSMTP):
    pass


def _email_settings(port):
    s = config.load_settings()
    s["tracker"]["email"].update(username="me@example.com", imap_host="imap.mail.me.com", smtp_port=port)
    config.save_secret("imap_password", "x")
    return s


ROW = [{"title": "Intern", "company": "Acme", "location": "", "url": "https://x"}]


def test_port_587_uses_starttls(alex, monkeypatch):
    _FakeSMTP.used = []
    monkeypatch.setattr(alerts.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", SMTP_SSL)
    assert alerts.email_self("t", ROW, _email_settings(587)) == ""
    assert _FakeSMTP.used == [("SMTP", 587), ("starttls", None)]


def test_port_465_uses_ssl(alex, monkeypatch):
    _FakeSMTP.used = []
    monkeypatch.setattr(alerts.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", SMTP_SSL)
    assert alerts.email_self("t", ROW, _email_settings(465)) == ""
    assert _FakeSMTP.used == [("SMTP_SSL", 465)]
