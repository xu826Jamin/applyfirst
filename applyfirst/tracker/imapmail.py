"""Read application mail over IMAP. Read only, by construction.

The mailbox is opened with readonly=True and messages are fetched with BODY.PEEK, so nothing
is marked seen. This module never calls store, copy, append, expunge, delete or any send.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import html
import imaplib
import re
from datetime import date, datetime, timedelta, timezone

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BODY_BYTES = 30000     # how much of each message is read; the body is only used to classify
BODY_CHARS = 4000      # and what is kept in memory for matching
CHUNK = 12             # search terms per SEARCH command, so no command grows too long
FETCH_BATCH = 40

# What application mail says. Turned from the original pipeline's Gmail query set into IMAP
# SEARCH keys: (field, term). SUBJECT matches the subject line, TEXT the whole message.
SEARCH_TERMS: list[tuple[str, str]] = [
    # subjects
    ("SUBJECT", "application"), ("SUBJECT", "applying"), ("SUBJECT", "applied"),
    ("SUBJECT", "interview"), ("SUBJECT", "assessment"), ("SUBJECT", "candidate"),
    ("SUBJECT", "next steps"), ("SUBJECT", "thank you for your interest"),
    ("SUBJECT", "offer"), ("SUBJECT", "action required"), ("SUBJECT", "action needed"),
    # actions and interviews
    ("TEXT", "hirevue"), ("TEXT", "codesignal"), ("TEXT", "hackerrank"),
    ("TEXT", "coding challenge"), ("TEXT", "phone screen"), ("TEXT", "schedule a call"),
    ("TEXT", "schedule a time"), ("TEXT", "pending task"), ("TEXT", "your availability"),
    ("TEXT", "pleased to offer"),
    # rejections and updates
    ("TEXT", "unfortunately"), ("TEXT", "moving forward"), ("TEXT", "not moving forward"),
    ("TEXT", "decided to proceed"), ("TEXT", "other candidates"),
    ("TEXT", "no longer under consideration"), ("TEXT", "position has been filled"),
    ("TEXT", "not selected"), ("TEXT", "regret to inform"), ("TEXT", "pursue other"),
    ("TEXT", "update on your application"), ("TEXT", "your application"),
]


def imap_date(d: date) -> str:
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def quote(term: str) -> str:
    return '"' + term.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _or_chain(keys: list[list[str]]) -> list[str]:
    if len(keys) == 1:
        return keys[0]
    return ["OR", *keys[0], *_or_chain(keys[1:])]


def build_searches(since: date) -> list[list[str]]:
    """The IMAP SEARCH criteria, one list per command: `SINCE d` AND (term OR term OR ...).
    Search keys only; no flag or state is ever set."""
    out = []
    for i in range(0, len(SEARCH_TERMS), CHUNK):
        keys = [[f, quote(t)] for f, t in SEARCH_TERMS[i:i + CHUNK]]
        out.append(["SINCE", imap_date(since), *_or_chain(keys)])
    return out


def connect(host: str, port: int, username: str, password: str):
    """IMAP over SSL. Kept as one small function so tests can substitute a stub."""
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(username, password)
    return conn


# --------------------------------------------------------------------------- parsing

def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return html.unescape(s)


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def _body_text(msg: email.message.EmailMessage) -> str:
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            text = part.get_content()
            return _strip_html(text) if part.get_content_type() == "text/html" else text
    except Exception:
        pass
    chunks = []
    for part in msg.walk():
        if part.get_content_maintype() != "text":
            continue
        try:
            text = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode("utf-8", "replace")
        chunks.append(_strip_html(text) if part.get_content_subtype() == "html" else text)
    return "\n".join(chunks)


def parse_message(raw: bytes) -> dict | None:
    """One raw message -> {id, thread_id, from, subject, date (ISO UTC), body}."""
    try:
        m = email.message_from_bytes(raw, policy=email.policy.default)
        subject = _plain(str(m.get("Subject") or ""))
        frm = _plain(str(m.get("From") or ""))
        body = _plain(_body_text(m))[:BODY_CHARS]
    except Exception:
        return None
    dt = None
    try:
        dt = email.utils.parsedate_to_datetime(str(m.get("Date") or ""))
    except (TypeError, ValueError, IndexError):
        pass
    if dt is None:
        iso = ""
    else:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        iso = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    mid = _plain(str(m.get("Message-ID") or "")).strip("<>")
    if not mid:
        mid = "hash-" + hashlib.sha256(f"{frm}|{iso}|{subject}".encode()).hexdigest()[:24]
    refs = _plain(str(m.get("References") or "") or str(m.get("In-Reply-To") or ""))
    thread = refs.split()[0].strip("<>") if refs else mid
    return {"id": mid, "thread_id": thread, "from": frm, "subject": subject, "date": iso,
            "body": body}


# --------------------------------------------------------------------------- fetching

def fetch_messages(conn, mailbox: str, since: date) -> list[dict]:
    """Search the mailbox read only and return the parsed messages (newest last)."""
    typ, _ = conn.select(mailbox, readonly=True)
    if typ != "OK":
        raise RuntimeError(f"Could not open the mailbox {mailbox!r} read-only.")
    uids: set[bytes] = set()
    for crit in build_searches(since):
        typ, data = conn.uid("SEARCH", None, *crit)
        if typ != "OK":
            raise RuntimeError("The mail server refused the search.")
        for chunk in data or []:
            if chunk:
                uids.update(chunk.split())
    ordered = sorted(uids, key=int)
    out: dict[str, dict] = {}
    for i in range(0, len(ordered), FETCH_BATCH):
        batch = b",".join(ordered[i:i + FETCH_BATCH]).decode()
        typ, data = conn.uid("FETCH", batch, f"(UID BODY.PEEK[]<0.{BODY_BYTES}>)")
        if typ != "OK":
            raise RuntimeError("The mail server refused to hand over messages.")
        for item in data or []:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                parsed = parse_message(bytes(item[1]))
                if parsed:
                    out.setdefault(parsed["id"], parsed)
    return sorted(out.values(), key=lambda m: m["date"])


def window_start(last_sync_iso: str | None, now: datetime, first_days: int = 35) -> date:
    """First run: the last 35 days. Later runs: since the last sync, with one day of overlap
    (every message is stored once, so reading a day twice is harmless)."""
    if last_sync_iso:
        try:
            last = datetime.fromisoformat(last_sync_iso)
            return (last - timedelta(days=1)).date()
        except ValueError:
            pass
    return (now - timedelta(days=first_days)).date()
