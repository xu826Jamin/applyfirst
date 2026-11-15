"""Write outcomes onto applications. The one place that moves an application's outcome.

Email outcomes only move forward: rejected < assessment < interview < offer. A later generic
"thanks for applying" never overwrites an interview, and a later rejection never erases the
fact that the application got an interview. `withdrawn` is the user's own act and is never
overridden by mail.
"""
from __future__ import annotations

import json

from .. import store
from . import classifier as C

OUTCOMES = ("rejected", "assessment", "interview", "offer", "withdrawn")
RANK = {"": 0, "rejected": 1, "assessment": 2, "interview": 3, "offer": 4, "withdrawn": 9}
CLASS_TO_OUTCOME = {"rejection": "rejected", "assessment": "assessment", "interview": "interview",
                    "offer": "offer"}
# Statuses where an email that proves the application went in lifts it to submitted.
BEFORE_SUBMIT = ("queued", "filling", "needs-you", "ready-to-submit", "failed")


def apply_class(app_id: int, cls: str, when: str, source: str = "email") -> str:
    """Apply what one email says to an application. Returns what changed, in plain words
    ('' when nothing changed)."""
    app = store.one("SELECT * FROM applications WHERE id=?", (app_id,))
    if not app:
        return ""
    now = store.now()
    if cls == "confirmation":
        changes = []
        sets: dict = {}
        if app["status"] in ("filling", "ready-to-submit"):
            sets["status"] = "submitted"
            changes.append("marked submitted")
        if (app["status"] in ("filling", "ready-to-submit", "submitted")
                and not app["submitted_at"] and when):
            sets["submitted_at"] = when
        if sets:
            _update(app_id, sets, now)
        return ", ".join(changes)
    outcome = CLASS_TO_OUTCOME.get(cls)
    if not outcome:
        return ""
    if RANK.get(outcome, 0) <= RANK.get(app["outcome"] or "", 0):
        return ""           # only forward
    sets = {"outcome": outcome, "outcome_at": when or now, "outcome_source": source}
    if app["status"] in BEFORE_SUBMIT:
        sets["status"] = "submitted"     # a reply is proof it went in
    _update(app_id, sets, now)
    return f"outcome {outcome}"


def _update(app_id: int, sets: dict, now: str) -> None:
    sets = {**sets, "updated_at": now}
    cols = ", ".join(f"{k}=?" for k in sets)
    store.execute(f"UPDATE applications SET {cols} WHERE id=?", (*sets.values(), app_id))


def set_manual_outcome(app_id: int, outcome: str) -> dict:
    """The user records an outcome by hand (any of them, in any order; '' clears it)."""
    if outcome not in ("", *OUTCOMES):
        raise ValueError(f"Outcome must be one of: {', '.join(OUTCOMES)} (or empty to clear).")
    app = store.one("SELECT * FROM applications WHERE id=?", (app_id,))
    if not app:
        raise LookupError("No such application.")
    now = store.now()
    if outcome == "":
        sets = {"outcome": "", "outcome_at": "", "outcome_source": ""}
    else:
        sets = {"outcome": outcome, "outcome_at": now, "outcome_source": "manual"}
        if app["status"] in BEFORE_SUBMIT:
            sets["status"] = "submitted"
    _update(app_id, sets, now)
    return store.one("SELECT * FROM applications WHERE id=?", (app_id,))


def learn_domain(sender: str, company_key: str) -> None:
    dom = C.sender_domain(sender)
    if dom and not C.is_ats(sender) and dom not in C.FREE_MAIL and company_key:
        store.execute("INSERT OR IGNORE INTO tracker_domains (domain, company_key) VALUES (?,?)",
                      (dom, company_key))


def match_message(message_id: int, app_id: int) -> dict:
    """The user places an unmatched email on an application. Applies what the email says
    and remembers the sender's domain for that employer."""
    from .matcher import employer_key
    msg = store.one("SELECT * FROM tracker_messages WHERE id=?", (message_id,))
    if not msg:
        raise LookupError("No such message.")
    app = store.one("SELECT * FROM applications WHERE id=?", (app_id,))
    if not app:
        raise LookupError("No such application.")
    store.execute(
        "UPDATE tracker_messages SET application_id=?, needs_match=0, match_note=? WHERE id=?",
        (app_id, "Placed by you.", message_id))
    changed = apply_class(app_id, msg["class"], msg["date"], "email")
    learn_domain(msg["sender"], employer_key(app["company"]))
    return {"message": message_row(message_id), "changed": changed or "nothing to change"}


def message_row(message_id: int) -> dict:
    r = store.one(
        "SELECT m.*, a.company AS app_company, a.title AS app_title FROM tracker_messages m "
        "LEFT JOIN applications a ON a.id = m.application_id WHERE m.id=?", (message_id,))
    return _present(r)


def _present(r: dict) -> dict:
    try:
        cand_ids = json.loads(r.get("candidates") or "[]")
    except ValueError:
        cand_ids = []
    cands = []
    for cid in cand_ids:
        a = store.one("SELECT id, company, title, status FROM applications WHERE id=?", (cid,))
        if a:
            cands.append(a)
    r["candidates"] = cands
    r["needs_match"] = bool(r["needs_match"])
    return r


def list_messages(unmatched: bool = False, limit: int = 200) -> list[dict]:
    where = "WHERE m.needs_match = 1" if unmatched else ""
    rows = store.rows(
        "SELECT m.*, a.company AS app_company, a.title AS app_title FROM tracker_messages m "
        f"LEFT JOIN applications a ON a.id = m.application_id {where} "
        "ORDER BY m.date DESC, m.id DESC LIMIT ?", (limit,))
    return [_present(r) for r in rows]
