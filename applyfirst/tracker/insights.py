"""stats(): what is actually getting interviews, broken down by what the user can change.

Honesty rules: every rate carries its sample size, and a group with fewer than MIN_POSITIVES
interviews is labelled "too few to compare" so nobody chases noise. A group is never dropped
because it looks bad.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .. import store

MIN_POSITIVES = 5
TOO_FEW = "too few to compare"
INTERVIEW_OUTCOMES = ("assessment", "interview", "offer")
RESPONSE_OUTCOMES = ("rejected", *INTERVIEW_OUTCOMES)
AGE_BUCKETS = ["under 24 hours", "1 to 3 days", "4 to 7 days", "older than a week"]
UNKNOWN_AGE = "unknown"


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def age_hours(first_seen: str | None, submitted: str | None) -> float | None:
    a, b = _dt(first_seen), _dt(submitted)
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds() / 3600)


def age_bucket(hours: float | None) -> str:
    if hours is None:
        return UNKNOWN_AGE
    if hours < 24:
        return AGE_BUCKETS[0]
    if hours < 96:
        return AGE_BUCKETS[1]
    if hours < 192:
        return AGE_BUCKETS[2]
    return AGE_BUCKETS[3]


def _rate(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def summarize(rows: list[dict], name: str | None = None) -> dict:
    """Counts and rates for a set of submitted applications, each with its sample size."""
    n = len(rows)
    responses = sum(1 for r in rows if r["outcome"] in RESPONSE_OUTCOMES)
    interviews = sum(1 for r in rows if r["outcome"] in INTERVIEW_OUTCOMES)
    enough = interviews >= MIN_POSITIVES
    out = {
        "applications": n,
        "responses": responses,
        "interviews": interviews,
        "response_rate": _rate(responses, n),
        "interview_rate": _rate(interviews, n),
        "sample_size": n,
        "enough_data": enough,
        "note": "" if enough else TOO_FEW,
    }
    if name is not None:
        out = {"group": name, **out}
    return out


def _group(rows: list[dict], keyfn, order: list[str] | None = None) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    names = list(groups)
    if order:
        names.sort(key=lambda g: (order.index(g) if g in order else len(order), g))
    else:
        names.sort(key=lambda g: (g == "unknown" or g.startswith("not recorded"), -len(groups[g]), g))
    return [summarize(groups[g], g) for g in names]


def _week_start(d: datetime) -> str:
    day = d.date()
    return (day - timedelta(days=day.weekday())).isoformat()


def _weekly(rows: list[dict]) -> list[dict]:
    weeks: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        when = _dt(r["submitted_at"]) or _dt(r["created_at"])
        if when:
            weeks[_week_start(when)].append(r)
    return [{**summarize(v), "week_start": k} for k, v in sorted(weeks.items())]


def _insights(by: dict[str, list[dict]]) -> list[str]:
    """Plain sentences, only where two or more groups each have enough interviews to compare."""
    labels = {"by_source": "Source", "by_resume": "Resume", "by_field": "Field",
              "by_level": "Level", "by_posting_age": "Speed"}
    out = []
    for key, groups in by.items():
        solid = [g for g in groups if g["enough_data"] and g["interview_rate"] is not None]
        if len(solid) < 2:
            continue
        solid.sort(key=lambda g: -g["interview_rate"])
        top, low = solid[0], solid[-1]
        if top["interview_rate"] <= low["interview_rate"]:
            continue
        out.append(
            f"{labels[key]}: {top['group']} leads at {top['interview_rate'] * 100:.0f}% "
            f"({top['interviews']} of {top['applications']}), against {low['group']} at "
            f"{low['interview_rate'] * 100:.0f}% ({low['interviews']} of {low['applications']}).")
    return out


def stats() -> dict:
    allrows = store.rows(
        "SELECT a.id, a.status, a.outcome, a.submitted_at, a.created_at, a.resume_file, "
        "p.source AS source, p.field AS field, p.level AS level, p.first_seen_at AS first_seen "
        "FROM applications a LEFT JOIN postings p ON p.id = a.posting_id")
    # An application counts once it went in: marked submitted, or it has an outcome (a reply
    # is proof it went in even if the status was never updated).
    rows = [r for r in allrows if r["status"] == "submitted" or r["outcome"]]
    for r in rows:
        r["age_hours"] = age_hours(r["first_seen"], r["submitted_at"])
    by = {
        "by_source": _group(rows, lambda r: r["source"] or "unknown"),
        "by_resume": _group(rows, lambda r: os.path.basename(r["resume_file"] or "")
                            or "not recorded"),
        "by_field": _group(rows, lambda r: r["field"] or "unknown"),
        "by_level": _group(rows, lambda r: r["level"] or "unknown"),
        "by_posting_age": _group(rows, lambda r: age_bucket(r["age_hours"]),
                                 order=[*AGE_BUCKETS, UNKNOWN_AGE]),
    }
    waiting = sum(1 for r in allrows if r["status"] in ("ready-to-submit", "needs-you"))
    unmatched = store.one("SELECT COUNT(*) AS c FROM tracker_messages WHERE needs_match=1")["c"]
    totals = summarize(rows)
    return {
        "totals": totals,
        "applications": totals["applications"],
        "responses": totals["responses"],
        "interviews": totals["interviews"],
        "interview_rate": totals["interview_rate"],
        "min_positives": MIN_POSITIVES,
        **by,
        "weekly": _weekly(rows),
        "insights": _insights(by),
        "unmatched_messages": unmatched,
        "waiting_for_you": waiting,
        "last_sync": (store.one("SELECT value FROM tracker_state WHERE key='last_sync_at'")
                      or {}).get("value", ""),
    }
