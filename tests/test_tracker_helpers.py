"""Shared helpers for the tracker tests: fictional emails, a stub IMAP server, seed data."""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone

from applyfirst import config, store

WRITE_COMMANDS = {"STORE", "COPY", "MOVE", "APPEND", "EXPUNGE", "DELETE", "CREATE", "RENAME",
                  "SETFLAGS"}


def raw_mail(sender: str, subject: str, body: str, when: str, mid: str,
             references: str = "") -> bytes:
    """A fictional email as raw RFC 822 bytes."""
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "alex.rivera@example.com"
    m["Subject"] = subject
    m["Date"] = format_datetime(datetime.fromisoformat(when).replace(tzinfo=timezone.utc))
    m["Message-ID"] = f"<{mid}@example.test>"
    if references:
        m["References"] = f"<{references}@example.test>"
    m.set_content(body)
    return m.as_bytes()


class StubIMAP:
    """Stands in for imaplib.IMAP4_SSL. Records every call; any write command raises."""

    instances: list["StubIMAP"] = []

    def __init__(self, messages: list[bytes]):
        self.messages = messages
        self.calls: list[tuple] = []
        self.selected = None
        self.readonly = None
        self.logged_out = False
        StubIMAP.instances.append(self)

    # session
    def select(self, mailbox="INBOX", readonly=False):
        self.calls.append(("select", mailbox, readonly))
        self.selected, self.readonly = mailbox, readonly
        return "OK", [b"%d" % len(self.messages)]

    def logout(self):
        self.logged_out = True
        return "BYE", []

    def uid(self, command, *args):
        cmd = command.upper()
        self.calls.append(("uid", cmd, *args))
        if cmd in WRITE_COMMANDS:
            raise AssertionError(f"tracker tried a write command: {cmd}")
        if cmd == "SEARCH":
            return "OK", [b" ".join(b"%d" % (i + 1) for i in range(len(self.messages)))]
        if cmd == "FETCH":
            ids = [int(x) for x in args[0].split(",")]
            out = []
            for i in ids:
                out.append((b"%d (UID %d BODY[]<0> {%d}" % (i, i, len(self.messages[i - 1])),
                            self.messages[i - 1]))
                out.append(b")")
            return "OK", out
        raise AssertionError(f"unexpected IMAP command {cmd}")

    # anything else a careless implementation might call
    def store(self, *a, **k):
        raise AssertionError("store called")

    def copy(self, *a, **k):
        raise AssertionError("copy called")

    def expunge(self, *a, **k):
        raise AssertionError("expunge called")

    def append(self, *a, **k):
        raise AssertionError("append called")


def configure_mail(host="imap.example.test", username="alex.rivera@example.com", password="pw"):
    s = config.load_settings()
    s["tracker"]["email"].update({"enabled": True, "imap_host": host, "username": username})
    config.save_settings(s)
    config.save_secret("imap_password", password)


def add_posting(pid: str, company: str, title: str, source="greenhouse", field="software",
                level="internship", first_seen="2026-11-01T09:00:00+00:00") -> str:
    store.upsert("postings", {"id": pid, "source": source, "company": company, "title": title,
                              "url": f"https://boards.example.test/{pid}", "field": field,
                              "level": level, "first_seen_at": first_seen})
    return pid


def add_app(company: str, title: str, status="submitted", posting_id=None, submitted_at="",
            created_at="2026-11-01T10:00:00+00:00", outcome="", resume_file="", notes="") -> int:
    return store.execute(
        "INSERT INTO applications (posting_id, company, title, status, submitted_at, created_at, "
        "updated_at, outcome, resume_file, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (posting_id, company, title, status, submitted_at, created_at, created_at, outcome,
         resume_file, notes))


def app(app_id: int) -> dict:
    return store.one("SELECT * FROM applications WHERE id=?", (app_id,))
