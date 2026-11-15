"""The judge: one posting, the user's settings and profile, a keep or skip with reasons.

Every check runs, so a skipped posting lists everything that ruled it out. A check that cannot
tell (no description yet, an unreadable location, no stated term) lets the posting through:
silence is not a mismatch. Reasons are plain language and shown to the user as written.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import dedupe, fields as F, levels as L, places as P, terms as T
from .text import clip, fold, has_phrase, join_words, now_utc, parse_dt

STUDENT_LEVELS = {"internship", "co-op", "new-grad"}
APPLIED_STATUSES = ("submitted", "ready-to-submit", "needs-you", "filling", "queued")


@dataclass
class Verdict:
    verdict: str = "keep"
    reasons: list = field(default_factory=list)   # why skipped, or why kept (plus notes)
    codes: list = field(default_factory=list)     # machine names of the failed checks

    @property
    def kept(self) -> bool:
        return self.verdict == "keep"


def _list(v: object) -> list:
    if not v:
        return []
    if isinstance(v, (list, tuple, set)):
        return [x for x in v if str(x).strip()]
    return [v] if str(v).strip() else []


def posting_levels(posting: dict) -> list[str]:
    found = L.detect_levels(posting.get("title") or "", posting.get("description") or "",
                            posting.get("raw"))
    stored = str(posting.get("level") or "").strip()
    if stored in L.LEVEL_ORDER and stored not in found:
        found = [lv for lv in L.LEVEL_ORDER if lv in set(found) | {stored}]
    return found


def posting_fields(posting: dict) -> list[str]:
    found, _ = F.detect_fields(posting.get("title") or "", posting.get("description") or "")
    stored = str(posting.get("field") or "").strip()
    if stored in F.FIELDS and stored not in found:
        found = [f for f in F.FIELDS if f in set(found) | {stored}]
    return found


def posting_term_months(posting: dict) -> list[int]:
    found = T.term_months(posting.get("title") or "", posting.get("description") or "")
    stored = posting.get("term_months")
    if isinstance(stored, int) and stored > 0 and stored not in found:
        found = sorted(set(found) | {stored})
    return found


def _ago(days: int) -> str:
    if days <= 0:
        return "Posted today"
    if days == 1:
        return "Posted yesterday"
    return f"Posted {days} days ago"


def _country_of(posting: dict) -> str:
    return P.norm_country(posting.get("country")) or P.infer_place(posting)[0]


def judge(posting: dict, settings: dict, profile: dict, now: dt.datetime | None = None,
          applied: list | None = None) -> Verdict:
    search = (settings or {}).get("search") or {}
    profile = profile or {}
    now = now or now_utc()
    today = now.date()
    title = str(posting.get("title") or "")
    desc = str(posting.get("description") or "")
    company = str(posting.get("company") or "")
    v = Verdict()
    keeps: list[str] = []
    notes: list[str] = []

    def fail(code: str, reason: str) -> None:
        v.codes.append(code)
        v.reasons.append(reason)

    # --- is it still a live, distinct posting
    if posting.get("alive") in (0, "0", False):
        fail("closed", "No longer listed on the company's site")
    if str(posting.get("duplicate_of") or "").strip():
        fail("duplicate", "Same job as another posting already in your list")
    phrase = T.closed_phrase(title + "\n" + desc)
    if phrase:
        fail("closed", f"The posting says it is closed (\"{clip(phrase, 40)}\")")
    deadline = T.stated_deadline(posting, today)
    if deadline and deadline < today.isoformat():
        fail("closed", f"The deadline passed on {deadline}")

    # --- company
    ck = dedupe.company_key(company)
    for name in _list(search.get("exclude_companies")):
        if ck and (dedupe.company_key(name) == ck or has_phrase(company, str(name))):
            fail("company", f"{clip(company, 40)} is on your list of companies to skip")
            break

    # --- level
    want_levels = [str(x) for x in _list(search.get("levels"))]
    levels = posting_levels(posting)
    if want_levels:
        hit = [lv for lv in levels if lv in want_levels]
        if hit:
            keeps.append(f"Matches your level: {hit[0]}")
        elif levels:
            fail("level", f"Looks like {L.label(levels)}, not {join_words(want_levels)}")
        elif not set(want_levels) - STUDENT_LEVELS:
            fail("level", "Not marked as an internship, co-op or new-grad role")
        # an unmarked posting stays when the user also wants entry, mid or senior roles

    # --- field
    want_fields = [str(x) for x in _list(search.get("fields"))]
    fields = posting_fields(posting)
    if want_fields and fields:
        hit = [f for f in fields if f in want_fields]
        if hit:
            keeps.append(f"Matches your field: {F.FIELD_LABEL.get(hit[0], hit[0])}")
        else:
            fail("field", f"Field is {F.label(fields)}, not {join_words([F.FIELD_LABEL.get(f, f) for f in want_fields])}")

    # --- location
    loc = P.check_location(posting, search)
    if not loc.ok:
        fail(loc.code or "location", loc.reason)
    elif loc.kept:
        keeps.append(loc.kept)

    # --- how old
    max_age = search.get("max_posting_age_days")
    posted = parse_dt(posting.get("posted_at")) or parse_dt(posting.get("first_seen_at"))
    if posted:
        days = max(0, (now - posted).days)
        if isinstance(max_age, (int, float)) and max_age > 0 and days > max_age:
            fail("age", f"Posted {days} days ago; your limit is {int(max_age)} days")
        else:
            keeps.append(_ago(days))

    # --- when it starts, how long it runs
    wanted_terms = [str(x) for x in _list(search.get("start_terms"))]
    if wanted_terms:
        fits, why = T.start_term_fits(T.start_terms(title, desc), wanted_terms)
        if not fits:
            fail("start", why)
    min_term = search.get("min_term_months")
    if isinstance(min_term, (int, float)) and min_term > 0:
        lengths = posting_term_months(posting)
        if lengths and max(lengths) < min_term:
            fail("term", f"A {max(lengths)}-month term; you want at least {int(min_term)} months")

    # --- languages the user cannot work in
    for lang in [str(x) for x in _list(search.get("skip_language_required"))]:
        name = lang.strip().capitalize()
        if T.language_flag(desc, lang, title) == "required":
            fail("language", f"Needs {name}")
        elif desc and T.posting_written_only_in(desc, lang):
            fail("language", f"The posting is written in {name} only")

    # --- keywords
    text = title + "\n" + desc
    includes = [str(x) for x in _list(search.get("include_keywords"))]
    if includes:
        if any(has_phrase(text, k) for k in includes):
            keeps.append("Mentions your keywords")
        elif len(desc.strip()) < 30:
            notes.append("Description not read yet, so your keywords were not checked")
        else:
            fail("keyword", f"Does not mention {join_words([clip(k, 20) for k in includes[:3]])}")
    for k in [str(x) for x in _list(search.get("exclude_keywords"))]:
        if has_phrase(text, k):
            fail("keyword", f"Mentions \"{clip(k, 30)}\", which you chose to leave out")
            break

    # --- who may apply
    cit = {P.norm_country(c) for c in _list(profile.get("citizenship"))}
    cit.discard("")
    us = T.us_only_phrase(text)
    if us:
        if cit and "US" not in cit:
            fail("citizenship", "Requires US citizenship or a US security clearance")
        elif not cit:
            notes.append("Asks for US citizenship or clearance; check you qualify")
    if T.no_sponsorship_phrase(desc):
        country = _country_of(posting)
        auth = {}
        for key, val in (profile.get("work_authorization") or {}).items():
            auth[P.norm_country(key)] = val if isinstance(val, dict) else {}
        mine = auth.get(country) if country else None
        if mine is not None and (mine.get("needs_sponsorship") or mine.get("authorized") is False):
            fail("sponsorship", f"No visa sponsorship, and you need it for {country}")
    schools = [str(e.get("school") or "") for e in _list(profile.get("education"))
               if isinstance(e, dict)]
    other_school = T.school_restriction(desc, schools)
    if other_school:
        notes.append(f"Mentions students of {clip(other_school, 40)}; the form may still accept you")

    # --- already applied
    for a in applied or []:
        same_id = a.get("posting_id") and a.get("posting_id") == posting.get("id")
        status = str(a.get("status") or "")
        if same_id:
            if status == "submitted":
                fail("applied", "You already applied to this")
                break
            continue
        if status in APPLIED_STATUSES and dedupe.is_repeat(company, title,
                                                           posting.get("location") or "", a):
            fail("applied", f"Looks like a role you already applied for at {clip(a.get('company'), 30)}")
            break

    if v.reasons:
        v.verdict = "skip"
    else:
        v.verdict = "keep"
        v.reasons = (keeps or ["Fits your settings"]) + notes
    return v
