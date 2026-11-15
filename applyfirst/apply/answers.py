"""The answers a form needs: derived from the profile, learned from earlier forms, or pending.

Three sources, in order of trust:
  1. standard_answers(): facts from the profile and settings (contact, links, education,
     work authorization per country, start date, term length, salary, demographics).
  2. learned answers: questions answered once (by the user, or by Claude from the profile)
     and stored in the `answers` table, reused by every later application.
  3. pending questions: a required question nobody has answered. The application stops as
     needs-you, the question waits in `answers` with pending=1, and the user answers it once.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from .. import config, store

COUNTRY_NAMES = {
    "CA": "Canada", "US": "United States", "GB": "United Kingdom", "IE": "Ireland",
    "AU": "Australia", "DE": "Germany", "FR": "France", "NL": "Netherlands", "IN": "India",
    "SG": "Singapore", "MX": "Mexico", "JP": "Japan", "NZ": "New Zealand", "CH": "Switzerland",
}

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

# Questions whose answer is written fresh for each posting. They are never stored for reuse.
PER_POSTING_RE = re.compile(
    r"why\b.*\b(company|us|you want|interested|this role|this position|hire|apply|join)|"
    r"cover letter|tell us about|anything else|additional information|"
    r"questions for us|what (excites|interests|motivates)|describe (a|your|how)",
    re.I,
)

HOW_HEARD = {
    "indeed": "Indeed", "linkedin": "LinkedIn", "glassdoor": "Glassdoor",
    "google": "Google", "school": "School job board", "email": "Job alert email",
}


# --------------------------------------------------------------------------- keys


def normalize_key(question: str) -> str:
    """Lowercase, punctuation and the required-star stripped, spaces collapsed."""
    s = re.sub(r"[^a-z0-9]+", " ", (question or "").lower())
    s = re.sub(r"\b(required|optional)\b\s*$", "", s.strip()).strip()
    return re.sub(r"\s+", " ", s)[:200]


# --------------------------------------------------------------------------- learned answers


def learn(question: str, answer: str, source: str = "user") -> bool:
    """Store an answer for a question; reused by every later application. False if empty."""
    key = normalize_key(question)
    answer = (answer or "").strip()
    if not key or not answer:
        return False
    if store.one("SELECT key FROM answers WHERE key=?", (key,)):
        # Keep the question as first seen and the use count.
        store.execute("UPDATE answers SET answer=?, source=?, pending=0, updated_at=? WHERE key=?",
                      (answer, source, store.now(), key))
    else:
        store.upsert("answers", {"key": key, "question": question.strip(), "answer": answer,
                                 "source": source, "pending": 0, "updated_at": store.now()}, key="key")
    return True


def learned_answers(limit: int = 150) -> list[dict]:
    """Answers worth showing Claude: answered, not from the profile, most used first."""
    return store.rows(
        "SELECT question, answer FROM answers WHERE pending=0 AND answer<>'' AND source<>'profile' "
        "ORDER BY uses DESC, updated_at DESC LIMIT ?", (limit,))


def mark_pending(application_id: int, question: str, qtype: str = "", options: list | None = None) -> bool:
    """Record a required question with no answer. False when an answer already exists."""
    key = normalize_key(question)
    if not key:
        return False
    existing = store.one("SELECT answer, pending FROM answers WHERE key=?", (key,))
    if existing and not existing["pending"] and existing["answer"]:
        return False
    if not existing:
        store.upsert("answers", {"key": key, "question": question.strip(), "answer": "",
                                 "source": "learned", "pending": 1, "updated_at": store.now()}, key="key")
    else:
        store.execute("UPDATE answers SET pending=1, updated_at=? WHERE key=?", (store.now(), key))
    _save_question(application_id, key, question, qtype, options)
    return True


def _save_question(application_id: int, key: str, question: str, qtype: str, options: list | None) -> None:
    store.execute(
        "INSERT OR REPLACE INTO application_questions (application_id, key, question, type, options, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (application_id, key, question.strip(), qtype or "", json.dumps(options or []), store.now()))


def pending_for(application_id: int) -> list[dict]:
    """Questions this application stopped on that are still unanswered."""
    return store.rows(
        "SELECT q.key, q.question, q.type, q.options FROM application_questions q "
        "JOIN answers a ON a.key=q.key WHERE q.application_id=? AND a.pending=1", (application_id,))


def questions_of(application_id: int) -> list[dict]:
    return store.rows("SELECT key, question, type, options FROM application_questions WHERE application_id=?",
                      (application_id,))


def _flatten(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _flatten(v)]
    if value in (None, ""):
        return []
    return [str(value).strip().lower()]


def record_used(answers_used: list[dict], standard: dict | None = None) -> dict:
    """Count uses of learned answers and learn new ones Claude reports typing.

    Answers that came straight from the profile, free-text written for one posting, and
    very long answers are not stored for reuse. Returns {"learned": n, "reused": n}.
    """
    standard_values = set(_flatten(standard or {}))
    learned = reused = 0
    for item in answers_used or []:
        if not isinstance(item, dict):
            continue
        q, a = str(item.get("question") or ""), str(item.get("answer") or "").strip()
        key = normalize_key(q)
        if not key or not a:
            continue
        row = store.one("SELECT answer, pending FROM answers WHERE key=?", (key,))
        if row and not row["pending"] and row["answer"]:
            store.execute("UPDATE answers SET uses=uses+1 WHERE key=?", (key,))
            reused += 1
        elif row:
            continue  # a pending question the user has not answered: Claude's text is not an answer
        elif (a.lower() in standard_values and a.lower() not in ("yes", "no")) or PER_POSTING_RE.search(q) or len(a) > 300:
            continue
        else:
            store.upsert("answers", {"key": key, "question": q.strip(), "answer": a, "source": "learned",
                                     "pending": 0, "uses": 1, "updated_at": store.now()}, key="key")
            learned += 1
    return {"learned": learned, "reused": reused}


# --------------------------------------------------------------------------- salary

_NUM = r"\d{1,3}(?:\.\d{1,2})?"
_BIG = r"\d{2,3}(?:,\d{3})+|\d{2,3}\s?[kK]"
HOURLY_RE = re.compile(
    rf"\$?\s*({_NUM})\s*(?:-|–|—|to)\s*\$?\s*({_NUM})\s*(?:/\s*|per\s+|an?\s+)?(?:hour|hr|h)\b", re.I)
ANNUAL_RE = re.compile(rf"\$\s*({_BIG})\s*(?:-|–|—|to)\s*\$?\s*({_BIG})", re.I)


def _money(text: str) -> float:
    t = text.replace(",", "").replace(" ", "").lower()
    return float(t[:-1]) * 1000 if t.endswith("k") else float(t)


def _clean(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:.2f}".rstrip("0").rstrip(".")


def salary_from_posting(posting: dict | None) -> dict | None:
    """The minimum of a stated pay range: {"amount", "unit": hour|year, "currency"} or None."""
    text = (posting or {}).get("description") or ""
    if not text:
        return None
    currency = ""
    m = re.search(r"\b(CAD|USD|GBP|EUR|AUD)\b|\b(C|US|CA|A)\$", text)
    if m:
        currency = m.group(1) or {"C": "CAD", "CA": "CAD", "US": "USD", "A": "AUD"}.get(m.group(2), "")
    h = HOURLY_RE.search(text)
    if h:
        lo, hi = float(h.group(1)), float(h.group(2))
        if 5 <= lo <= hi <= 500:
            return {"amount": _clean(lo), "unit": "hour", "currency": currency}
    a = ANNUAL_RE.search(text)
    if a:
        lo, hi = _money(a.group(1)), _money(a.group(2))
        if 15000 <= lo <= hi <= 2_000_000:
            return {"amount": _clean(lo), "unit": "year", "currency": currency}
    return None


# --------------------------------------------------------------------------- standard answers


def _yes(flag: Any) -> str:
    return "Yes" if flag else "No"


def _fmt_date(iso: str) -> dict:
    try:
        d = date.fromisoformat(iso[:10])
    except (ValueError, TypeError):
        return {"iso": iso or "", "mdy": "", "text": ""}
    return {"iso": d.isoformat(), "mdy": d.strftime("%m/%d/%Y"), "my": d.strftime("%m/%Y"),
            "text": f"{MONTHS[d.month - 1]} {d.year}"}


def _fmt_month(ym: str) -> dict:
    try:
        y, m = (int(x) for x in str(ym).split("-")[:2])
        return {"iso": f"{y:04d}-{m:02d}", "my": f"{m:02d}/{y:04d}", "text": f"{MONTHS[m - 1]} {y}"}
    except (ValueError, TypeError, IndexError):
        return {"iso": ym or "", "my": "", "text": ""}


def standard_answers(profile: dict, settings: dict, posting: dict | None = None) -> dict:
    """The answers derived from the profile, ready to give a form-filler.

    `posting` is optional; with it the salary comes from the posting's stated range and
    the work-authorization answer for the posting's own country is spelled out.
    """
    posting = posting or {}
    name = profile.get("name") or {}
    loc = profile.get("location") or {}
    links = profile.get("links") or {}
    avail = profile.get("availability") or {}

    first, last = name.get("first", ""), name.get("last", "")
    contact = {
        "first_name": first, "last_name": last,
        "preferred_name": name.get("preferred") or first,
        "full_name": f"{first} {last}".strip(),
        "email": profile.get("email", ""), "phone": profile.get("phone", ""),
        "city": loc.get("city", ""), "region": loc.get("region", ""),
        "country_code": loc.get("country", ""),
        "country": COUNTRY_NAMES.get(loc.get("country", ""), loc.get("country", "")),
        "postal_code": loc.get("postal_code", ""),
        "location_text": ", ".join(x for x in (loc.get("city"), loc.get("region"),
                                                COUNTRY_NAMES.get(loc.get("country", ""), loc.get("country"))) if x),
    }

    edu_list = profile.get("education") or []
    current = next((e for e in edu_list if e.get("current")), edu_list[0] if edu_list else {})
    education = {
        "school": current.get("school", ""), "degree": current.get("degree", ""),
        "field_of_study": current.get("field", ""),
        "start": _fmt_month(current.get("start", "")), "graduation": _fmt_month(current.get("end", "")),
        "gpa": current.get("gpa", ""), "gpa_scale": current.get("gpa_scale", ""),
        "currently_enrolled": _yes(current.get("current")),
        "history": edu_list,
    }

    work_auth: dict[str, dict] = {}
    for code, entry in (profile.get("work_authorization") or {}).items():
        work_auth[code] = {
            "country": COUNTRY_NAMES.get(code, code),
            "authorized": _yes(entry.get("authorized")),
            "needs_sponsorship": _yes(entry.get("needs_sponsorship")),
        }
    pcountry = (posting.get("country") or "").upper()
    for_posting = dict(work_auth[pcountry], country_code=pcountry) if pcountry in work_auth else None

    terms = [int(t) for t in (avail.get("term_months") or []) if str(t).isdigit() or isinstance(t, int)]
    if terms:
        term = {"months": sorted(terms), "longest": max(terms),
                "text": f"Up to {max(terms)} months ({', '.join(str(t) for t in sorted(terms))} month terms)"}
    else:
        term = {"months": [], "longest": None, "text": ""}

    relocate_flag = avail.get("willing_to_relocate", True)
    policy = config.get(settings, "apply.future_commitments", "yes")
    if policy == "yes":
        commitments = {"policy": "yes", "willing_to_relocate": "Yes", "willing_to_travel": "Yes",
                       "onsite_or_hybrid": "Yes", "shift_work_or_overtime": "Yes",
                       "available_on_start_date": "Yes", "scheduled_for_work_term": "Yes"}
    else:
        commitments = {"policy": "literal", "willing_to_relocate": _yes(relocate_flag)}

    salary = None
    stated = salary_from_posting(posting)
    prof_sal = profile.get("salary") or {}
    if stated:
        cur = stated["currency"] or prof_sal.get("currency", "")
        salary = {"amount": stated["amount"], "unit": stated["unit"], "currency": cur,
                  "source": "posting range minimum"}
    elif prof_sal.get("hourly_min"):
        salary = {"amount": _clean(float(prof_sal["hourly_min"])), "unit": "hour",
                  "currency": prof_sal.get("currency", ""), "source": "profile"}
    elif prof_sal.get("annual_min"):
        salary = {"amount": _clean(float(prof_sal["annual_min"])), "unit": "year",
                  "currency": prof_sal.get("currency", ""), "source": "profile"}
    if salary:
        salary["text"] = f"{salary['amount']} {salary['currency']} per {salary['unit']}".replace("  ", " ")

    demo = {k: (v or "") for k, v in (profile.get("demographics") or {}).items()}

    return {
        "contact": contact,
        "links": {"linkedin": links.get("linkedin", ""), "github": links.get("github", ""),
                  "portfolio": links.get("portfolio", ""), "other": links.get("other") or []},
        "education": education,
        "citizenship": [COUNTRY_NAMES.get(c, c) for c in (profile.get("citizenship") or [])],
        "work_authorization": work_auth,
        "work_authorization_for_this_posting": for_posting,
        "start_date": _fmt_date(avail.get("earliest_start", "")),
        "term_length": term,
        "commitments": commitments,
        "salary": salary,
        "languages": profile.get("languages") or [],
        "demographics": demo,
        "demographics_note": "An empty value means decline to answer: choose the 'prefer not to say' style option.",
        "how_did_you_hear": HOW_HEARD.get((posting.get("source") or "").lower(), "Company website"),
    }


def workday_answers(std: dict, posting: dict | None = None) -> dict:
    """The flat answers object workday_fill.js takes, built from standard_answers()."""
    posting = posting or {}
    c, edu = std["contact"], std["education"]
    out: dict[str, Any] = {
        "firstName": c["first_name"], "lastName": c["last_name"], "email": c["email"],
        "phone": c["phone"], "phoneDeviceType": "Mobile", "city": c["city"], "state": c["region"],
        "postalCode": c["postal_code"], "country": c["country"],
        "linkedin": std["links"]["linkedin"], "github": std["links"]["github"],
        "school": edu["school"], "degree": edu["degree"], "fieldOfStudy": edu["field_of_study"],
        "gradDate": edu["graduation"].get("my", ""), "schoolStart": edu["start"].get("my", ""),
        "gpa": edu["gpa"], "gpaScale": edu["gpa_scale"],
        "startDate": std["start_date"].get("mdy", ""), "termLength": std["term_length"]["text"],
        "relocate": std["commitments"].get("willing_to_relocate", ""),
        "howHeard": std["how_did_you_hear"],
        "citizenship": std["citizenship"][0] if std["citizenship"] else "",
        "workAuth": {code: {"authorized": e["authorized"], "sponsorship": e["needs_sponsorship"]}
                     for code, e in std["work_authorization"].items()},
        "defaultCountry": (posting.get("country") or c["country_code"] or "").upper(),
        "demographics": std["demographics"],
    }
    if std["salary"]:
        out["salary"] = std["salary"]["amount"]
    return {k: v for k, v in out.items() if v not in ("", None)} | {"demographics": std["demographics"]}
