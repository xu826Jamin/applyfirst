"""Emailed security codes that finish an application, read from the person's own inbox.

Some forms (Greenhouse, for one) email a short code after Submit and wait for it in a box on the
form. Only the Claude session that filled the form can still reach that tab, so this module runs
as a one-tool MCP server for that session: `wait_for_email_code` polls the inbox (read only, the
same settings as Email replies) and returns just the code.

Narrow on purpose, because the session also reads job pages written by strangers:
- only mail that arrived after this application started is looked at (the start time is fixed
  by applyfirst when the server starts, never chosen by the model);
- only a code is returned, never a subject, sender or body;
- sign-in, login, password and account codes are refused: those unlock accounts, and
  applyfirst never signs in for the person.

Run as: python -m applyfirst.apply.email_code   (stdio JSON-RPC, MCP)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

TOOL = "wait_for_email_code"
DEFAULT_WAIT = 120
MAX_WAIT = 300
POLL_SECONDS = 15

_CODE_WORDS = re.compile(r"\b(security|verification|confirmation|one[- ]time|access)?\s*code\b", re.I)
# Codes that unlock an account rather than finish an application.
_ACCOUNT = re.compile(r"sign[- ]?in|log[- ]?in|login|password|reset|my ?greenhouse|account|two[- ]factor|2fa", re.I)
_APPLICATION = re.compile(r"application|apply|applied|candidate|resubmit", re.I)
_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{4,10})(?![A-Za-z0-9])")


def extract_code(msg: dict, company: str = "") -> str | None:
    """The application code in one parsed message ({from, subject, body}), or None."""
    subject, body = msg.get("subject") or "", msg.get("body") or ""
    text = f"{subject}\n{body}"
    if _ACCOUNT.search(subject) or _ACCOUNT.search(body[:600]):
        return None
    if not _APPLICATION.search(text):
        return None
    for m in _CODE_WORDS.finditer(text):
        window = text[m.end(): m.end() + 120]
        for t in _TOKEN.finditer(window):
            tok = t.group(1)
            if any(ch.isdigit() for ch in tok) and not re.fullmatch(r"(19|20)\d\d", tok):
                return tok
    return None


def pick(messages: list[dict], since: datetime, company: str = "") -> str | None:
    """The newest application code among messages that arrived after `since`."""
    best = None
    for msg in messages:
        try:
            when = datetime.fromisoformat(msg.get("date") or "")
        except ValueError:
            continue
        if when < since:
            continue
        code = extract_code(msg, company)
        if not code:
            continue
        named = bool(company) and company.lower() in f"{msg.get('subject')} {msg.get('body')}".lower()
        rank = (named, when)
        if best is None or rank > best[0]:
            best = (rank, code)
    return best[1] if best else None


def _fetch_recent(since: datetime) -> list[dict]:
    """Messages from today and yesterday that mention a code. Read only (BODY.PEEK)."""
    from .. import config
    from ..tracker import imapmail, syncer
    cfg = syncer.email_config()
    password = config.load_secrets().get("imap_password") or ""
    if not cfg or not password:
        raise RuntimeError("Email is not connected in Settings.")
    conn = imapmail.connect(cfg["imap_host"], int(cfg.get("imap_port") or 993), cfg["username"], password)
    try:
        typ, _ = conn.select(cfg.get("mailbox") or "INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError("Could not open the mailbox read-only.")
        day = imapmail.imap_date((since - timedelta(days=1)).date())
        typ, data = conn.uid("SEARCH", None, "SINCE", day, "OR", "SUBJECT", '"code"', "TEXT", '"code"')
        if typ != "OK":
            raise RuntimeError("The mail server refused the search.")
        uids = sorted({u for chunk in data or [] if chunk for u in chunk.split()}, key=int)[-25:]
        out = []
        if uids:
            typ, data = conn.uid("FETCH", b",".join(uids).decode(), f"(UID BODY.PEEK[]<0.{imapmail.BODY_BYTES}>)")
            for item in data or []:
                if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                    m = imapmail.parse_message(bytes(item[1]))
                    if m:
                        out.append(m)
        return out
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def wait_for_code(since: datetime, company: str, max_wait: int, fetch=_fetch_recent, sleep=time.sleep) -> str:
    """Poll until a code arrives or the wait runs out. Returns the text the tool answers with."""
    try:
        wait = DEFAULT_WAIT if max_wait is None else int(max_wait)
    except (TypeError, ValueError):
        wait = DEFAULT_WAIT
    deadline = time.monotonic() + max(0, min(wait, MAX_WAIT))
    while True:
        try:
            code = pick(fetch(since), since, company)
        except Exception as e:
            return f"Could not read the inbox: {e}"
        if code:
            return f"CODE: {code}"
        if time.monotonic() >= deadline:
            return "No code email arrived. Leave the tab on the code box and report needs-you."
        sleep(POLL_SECONDS)


def is_available() -> bool:
    """True when email is connected well enough for the server to read codes."""
    from .. import config
    from ..tracker import syncer
    return bool(syncer.email_config() and config.load_secrets().get("imap_password"))


def server_config(company: str) -> dict:
    """The --mcp-config entry for one application run."""
    import applyfirst
    root = os.path.dirname(os.path.dirname(os.path.abspath(applyfirst.__file__)))
    from .. import config
    return {"command": sys.executable, "args": ["-m", "applyfirst.apply.email_code"],
            "env": {"APPLYFIRST_HOME": str(config.home()), "PYTHONPATH": root,
                    "APPLYFIRST_CODE_SINCE": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                    "APPLYFIRST_CODE_COMPANY": company or ""}}


# --------------------------------------------------------------------------- MCP over stdio

_TOOL_DEF = {
    "name": TOOL,
    "description": ("Waits for the security code this application just emailed to the person and "
                    "returns only the code. Use it only when the form, after Submit, asks for a code "
                    "sent to the person's email to finish the application. It never returns sign-in "
                    "or account codes."),
    "inputSchema": {"type": "object", "properties": {
        "max_wait_seconds": {"type": "integer", "minimum": 0, "maximum": MAX_WAIT,
                             "description": f"How long to wait for the email (default {DEFAULT_WAIT})."}}},
}


def _reply(msg_id, result=None, error=None) -> None:
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def serve() -> None:
    since = datetime.fromisoformat(os.environ.get("APPLYFIRST_CODE_SINCE")
                                   or datetime.now(timezone.utc).isoformat())
    company = os.environ.get("APPLYFIRST_CODE_COMPANY", "")
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, msg_id = req.get("method"), req.get("id")
        if msg_id is None:
            continue                                     # notifications need no answer
        if method == "initialize":
            ver = (req.get("params") or {}).get("protocolVersion") or "2025-06-18"
            _reply(msg_id, {"protocolVersion": ver, "capabilities": {"tools": {}},
                            "serverInfo": {"name": "applyfirst", "version": "1"}})
        elif method == "tools/list":
            _reply(msg_id, {"tools": [_TOOL_DEF]})
        elif method == "tools/call":
            p = req.get("params") or {}
            if p.get("name") != TOOL:
                _reply(msg_id, error={"code": -32602, "message": "Unknown tool."})
                continue
            text = wait_for_code(since, company, (p.get("arguments") or {}).get("max_wait_seconds", DEFAULT_WAIT))
            _reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": text.startswith("Could not")})
        elif method == "ping":
            _reply(msg_id, {})
        else:
            _reply(msg_id, error={"code": -32601, "message": "Method not found."})


if __name__ == "__main__":
    serve()
