"""sync(run_id): read new mail, classify it, place it on applications, record outcomes."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .. import config, store
from . import classifier as C
from . import imapmail, matcher, record

NOT_SET_UP = ("Email is not set up, so replies cannot be read automatically. Add your mailbox "
              "under Settings to turn that on. You can still record outcomes by hand on any "
              "application.")


def _state(key: str) -> str | None:
    r = store.one("SELECT value FROM tracker_state WHERE key=?", (key,))
    return r["value"] if r else None


def _set_state(key: str, value: str) -> None:
    store.upsert("tracker_state", {"key": key, "value": value}, key="key")


def email_config() -> dict | None:
    """The mailbox settings when sync can run, else None."""
    s = config.load_settings()
    cfg = dict(config.get(s, "tracker.email") or {})
    if not (cfg.get("enabled") and cfg.get("imap_host") and cfg.get("username")):
        return None
    return cfg


def sync(run_id: str) -> str:
    cfg = email_config()
    if cfg is None:
        store.log(run_id, "Email is not configured; nothing to read.")
        return NOT_SET_UP
    password = config.load_secrets().get("imap_password") or ""
    if not password:
        store.log(run_id, "No mail password stored.")
        return ("Email is set up but no mail password is saved yet, so nothing was read. "
                "Add the password under Settings.")
    started = datetime.now(timezone.utc)
    since = imapmail.window_start(_state("last_sync_at"), started)
    first = _state("last_sync_at") is None
    store.log(run_id, f"Reading mail since {since.isoformat()} "
                      f"({'first run' if first else 'since the last sync'}).")
    try:
        conn = imapmail.connect(cfg["imap_host"], int(cfg.get("imap_port") or 993),
                                cfg["username"], password)
    except Exception as e:
        raise RuntimeError(f"Could not sign in to the mail server: {_plain_error(e)}") from None
    try:
        msgs = imapmail.fetch_messages(conn, cfg.get("mailbox") or "INBOX", since)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    store.log(run_id, f"{len(msgs)} candidate messages fetched.")
    summary = process(msgs, run_id, own_address=cfg["username"])
    _set_state("last_sync_at", started.isoformat(timespec="seconds"))
    _set_state("last_summary", summary)
    return summary


def _plain_error(e: Exception) -> str:
    text = str(e) or e.__class__.__name__
    if isinstance(e, bytes):
        text = e.decode("utf-8", "replace")
    return text.replace("b'", "").replace("'", "")[:160]


def process(msgs: list[dict], run_id: str, own_address: str = "") -> str:
    """Classify, place and record a batch of parsed messages. Already-seen messages (by
    Message-ID) are skipped, so overlapping windows and re-runs change nothing."""
    own = own_address.lower()
    fresh = []
    for m in msgs:
        if own and C.sender_addr(m["from"]) == own:
            continue    # mail the user sent is never a reply
        if store.one("SELECT 1 AS x FROM tracker_messages WHERE message_id=?", (m["id"],)):
            continue
        fresh.append(m)
    learned = {r["domain"]: r["company_key"] for r in store.rows("SELECT * FROM tracker_domains")}
    pool = matcher.Pool(matcher.load_pool(), learned)
    results, new_domains = matcher.analyze(fresh, pool)
    for dom, key in new_domains.items():
        store.execute("INSERT OR IGNORE INTO tracker_domains (domain, company_key) VALUES (?,?)",
                      (dom, key))
    counts = {"confirmation": 0, "rejection": 0, "assessment": 0, "interview": 0, "offer": 0,
              "other": 0}
    placed = unmatched = skipped = changed = 0
    for r in results:
        m = r["msg"]
        if not r["trusted"]:
            skipped += 1
            continue
        cls = r["class"]
        app_id = r["app_ids"][0] if r["app_ids"] else None
        needs = 1 if (cls != "other" and app_id is None) else 0
        store.execute(
            "INSERT INTO tracker_messages (message_id, thread_id, subject, sender, date, class, "
            "application_id, match_note, candidates, needs_match, run_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (m["id"], m.get("thread_id", ""), m["subject"][:300], m["from"][:200], m["date"],
             cls, app_id, r["reason"][:300], json.dumps(r["candidates"]), needs, run_id,
             store.now()))
        counts[cls] += 1
        if app_id is not None:
            placed += 1
            if cls != "other" and record.apply_class(app_id, cls, m["date"], "email"):
                changed += 1
        elif needs:
            unmatched += 1
        store.log(run_id, f"{cls}: {m['subject'][:80]} -> "
                          f"{'application ' + str(app_id) if app_id else 'unmatched'} ({r['reason']})")
    replies = counts["rejection"] + counts["assessment"] + counts["interview"] + counts["offer"]
    parts = [f"Read {len(fresh)} new emails: {counts['confirmation']} confirmations, "
             f"{replies} replies ({counts['interview']} interviews, {counts['assessment']} "
             f"assessments, {counts['offer']} offers, {counts['rejection']} rejections)."]
    parts.append(f"{changed} applications updated.")
    if unmatched:
        parts.append(f"{unmatched} need you to say which application they belong to.")
    if skipped:
        parts.append(f"{skipped} were not application mail and were ignored.")
    return " ".join(parts)
