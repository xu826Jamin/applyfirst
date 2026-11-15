"""classify, evaluate, evaluate_all, queue: the filters package's public behaviour."""
from __future__ import annotations

import datetime as dt
import json

from .. import config, store
from . import fields as F, gate, levels as L, places as P, terms as T
from .ordering import experience_profile, order, rough_match
from .text import now_utc

VIEWS = ("kept", "approved", "skipped", "all")


# --------------------------------------------------------------------------- classify


def classify(posting: dict, force: bool = False, today: dt.date | None = None) -> dict:
    """A copy of the posting with level, field, term_months, deadline, country (and region)
    filled from its title, description and location. Empty values are always filled; with
    force=True level, field and term_months are recomputed (the sources never set them, so the
    filters own them). A deadline is stored only when the text states its year, and a country
    only when the location settles one. A posting is never changed in place."""
    p = dict(posting)
    title = str(p.get("title") or "")
    desc = str(p.get("description") or "")
    today = today or now_utc().date()

    if force or not str(p.get("level") or "").strip():
        levels = L.detect_levels(title, desc, p.get("raw"))
        if levels or force:
            p["level"] = L.primary(levels)
    if force or not str(p.get("field") or "").strip():
        found, _ = F.detect_fields(title, desc)
        if found or force:
            p["field"] = found[0] if found else ""
    if force or not p.get("term_months"):
        lengths = T.term_months(title, desc)
        if lengths or force:
            p["term_months"] = max(lengths) if lengths else None
    if not str(p.get("deadline") or "").strip():
        p["deadline"] = T.stated_deadline({**p, "deadline": ""}, today)
    country, region = P.infer_place(p)
    if not str(p.get("country") or "").strip() and country:
        p["country"] = country
    p["region"] = region
    for key in ("level", "field", "deadline", "country"):
        p[key] = p.get(key) or ""
    p.setdefault("term_months", None)
    any_remote, fully = P.is_remote(p)
    if fully and not p.get("remote"):
        p["remote"] = 1
    return p


# --------------------------------------------------------------------------- evaluate


def evaluate(posting: dict, settings: dict, profile: dict, now: dt.datetime | None = None,
             applied: list | None = None) -> tuple[str, list[str]]:
    """('keep' | 'skip', plain-language reasons) for one posting. Reasons say why it was skipped
    (every check that failed), or what it matched when kept, plus any notes worth a look."""
    v = gate.judge(posting, settings, profile, now=now, applied=applied)
    return v.verdict, list(v.reasons)


def _applied_rows() -> list[dict]:
    return store.rows(
        "SELECT a.posting_id, a.company, a.title, a.status, COALESCE(p.location,'') AS location "
        "FROM applications a LEFT JOIN postings p ON p.id = a.posting_id")


def _log(run_id: str | None, line: str) -> None:
    if run_id:
        store.log(run_id, line)


def evaluate_all(run_id: str | None = None, ids: list[str] | None = None) -> dict:
    """Classify and evaluate every live, non-duplicate posting (or only `ids`, used mid-sweep)
    and write verdict and verdict_reasons. Returns counts: total, evaluated, kept, skipped,
    new_kept (kept now but not before), by_reason (skip reasons by check), summary."""
    settings = config.load_settings()
    profile = config.load_profile()
    now = now_utc()
    applied = _applied_rows()
    sql = "SELECT * FROM postings WHERE alive=1 AND COALESCE(duplicate_of,'')=''"
    if ids is not None:
        rows = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            rows += store.rows(sql + f" AND id IN ({','.join('?' * len(chunk))})", chunk)
    else:
        rows = store.rows(sql)
    kept = skipped = new_kept = 0
    by_reason: dict[str, int] = {}
    updates = []
    for row in rows:
        before = row.get("verdict") or ""
        c = classify(row, force=True, today=now.date())
        v = gate.judge(c, settings, profile, now=now, applied=applied)
        verdict, reasons = v.verdict, list(v.reasons)
        if verdict == "keep":
            kept += 1
            if before != "keep":
                new_kept += 1
        else:
            skipped += 1
            for code in dict.fromkeys(v.codes):
                by_reason[code] = by_reason.get(code, 0) + 1
        updates.append((c.get("level") or "", c.get("field") or "", c.get("term_months"),
                        c.get("deadline") or "", c.get("country") or "", verdict,
                        json.dumps(reasons), row["id"]))
    con = store.db()
    con.executemany(
        "UPDATE postings SET level=?, field=?, term_months=?, deadline=?, country=?, "
        "verdict=?, verdict_reasons=? WHERE id=?", updates)
    con.commit()
    summary = (f"{kept:,} of {len(rows):,} postings match your settings"
               + (f", {new_kept:,} of them new." if new_kept else "."))
    _log(run_id, summary)
    for code, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        _log(run_id, f"  skipped for {code}: {n}")
    return {"total": len(rows), "evaluated": len(rows), "kept": kept, "skipped": skipped,
            "new_kept": new_kept, "by_reason": by_reason, "summary": summary}


# --------------------------------------------------------------------------- queue

_LIVE = "alive=1 AND COALESCE(duplicate_of,'')=''"


def _with_reasons(row: dict) -> dict:
    row = dict(row)
    try:
        r = json.loads(row.get("verdict_reasons") or "[]")
    except ValueError:
        r = []
    row["reasons"] = r if isinstance(r, list) else []
    return row


_VIEW_WHERE = {
    "kept": "verdict='keep' AND COALESCE(user_action,'')=''",
    "approved": "user_action='approved'",
    "skipped": "user_action='skipped' OR (verdict='skip' AND COALESCE(user_action,'')<>'approved')",
    "all": "1=1",
}
# Everything but `raw` (the source's whole download, never shown): reading it for every row
# made a Jobs page with a few thousand postings take seconds.
_COLUMNS = ("id, source, company, title, location, remote, country, url, apply_url, ats, "
            "description, posted_at, first_seen_at, deadline, level, field, term_months, "
            "fingerprint, duplicate_of, alive, verdict, verdict_reasons, user_action")


def view_rows(view: str) -> list[dict]:
    if view not in VIEWS:
        raise ValueError(f"view must be one of {', '.join(VIEWS)}")
    return [_with_reasons(r) for r in store.rows(
        f"SELECT {_COLUMNS} FROM postings WHERE {_LIVE} AND ({_VIEW_WHERE[view]})")]


def queue(settings: dict, view: str = "kept", limit: int = 100) -> list[dict]:
    """The postings in one view, in the user's order. Views: kept (verdict keep, no action yet),
    approved, skipped (by the user or by the filters), all. Rows are the full posting plus
    `reasons` (a list), and `rough_match` when the order uses it."""
    rows = view_rows(view)
    experience = store.rows("SELECT * FROM experience WHERE confirmed=1")
    ordered = order(rows, settings, experience=experience)
    if limit is not None and limit >= 0:
        ordered = ordered[:limit]
    # The match score costs about 10 ms a posting; only work it out when the order uses it.
    q = settings.get("queue") or {}
    if "match" in (q.get("order_by"), q.get("then_by")):
        terms, tags = experience_profile(experience)
        for p in ordered:
            p["rough_match"] = rough_match(p, terms, tags)
    return ordered


def counts() -> dict:
    out = {}
    for v in VIEWS:
        r = store.one(f"SELECT COUNT(*) n FROM postings WHERE {_LIVE} AND ({_VIEW_WHERE[v]})")
        out[v] = r["n"] if r else 0
    return out
