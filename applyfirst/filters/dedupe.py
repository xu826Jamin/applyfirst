"""Have I already applied to this? Same employer, same role words, same place.

Ported from an earlier version's duplicate check: legal suffixes drop off a company name, the
words that identify a role are what is left once terms, ids and levels go, two terms of one role
are two postings, and a different city is a different requisition.
"""
from __future__ import annotations

import re

_LEGAL = {"inc", "incorporated", "corp", "corporation", "ltd", "limited", "llc", "llp", "lp", "plc",
          "co", "company", "gmbh", "ag", "sa", "bv", "the", "canada", "canadian", "usa", "us", "group",
          "holdings", "technologies", "technology", "labs"}
_NOISE = {
    "the", "of", "and", "for", "in", "at", "a", "an", "to", "with", "de", "du", "des", "en", "et",
    "la", "le", "les", "new", "position", "positions", "program", "opportunity", "opportunities",
    "or", "full", "time", "part", "f", "h", "x", "m", "w", "d", "intern", "internship", "co", "op",
    "coop", "student", "junior", "senior", "sr", "jr", "remote", "hybrid", "onsite", "term",
    "months", "month", "ca", "us", "usa", "on", "bc", "ab", "qc",
}
_TERM_ALIAS = {"january": "winter", "jan": "winter", "may": "summer", "september": "fall",
               "sept": "fall"}
_TERM_WORDS = frozenset({"winter", "summer", "fall", "spring", "autumn"})
_PLACE_JUNK = {"on", "ont", "ontario", "ab", "bc", "qc", "mb", "sk", "ns", "nb", "nl", "pe", "canada",
               "remote", "hybrid", "on-site", "onsite", "flexible", "us", "usa", "unknown",
               "united states", "california", "texas", "new york", "uk", "united kingdom"}


def company_key(name: object) -> str:
    s = re.sub(r"\([^)]*\)", " ", str(name or "").lower())
    words = re.sub(r"[^a-z0-9]+", " ", s).split()
    while len(words) > 1 and words[-1] in _LEGAL:
        words.pop()
    return " ".join(words)


def same_company(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return long_[:len(short)] == short and len(short[0]) >= 3


def role_words(title: object) -> frozenset:
    t = str(title or "").lower()
    t = re.sub(r"\([^)]*\b(?:greenhouse|ashby|lever|workday|smartrecruiters|job|req|id)\b[^)]*\)", " ", t)
    t = re.sub(r"\b\d+\s*(?:[-/+]\s*\d+\s*)?\+?\s*(?:months?|mois)\b", " ", t)
    words = set()
    for w in re.sub(r"[^a-z0-9]+", " ", t).split():
        if w in _NOISE:
            continue
        if sum(ch.isdigit() for ch in w) >= 4 and not re.fullmatch(r"20\d\d", w):
            continue          # a requisition id such as r1002165 or 8797859002 (not a year)
        words.add(_TERM_ALIAS.get(w, w))
    return frozenset(words)


def _variants(title: object) -> set:
    parts = re.split(r"\s[/|]\s", str(title or ""))
    out = {role_words(title)} | {role_words(p) for p in parts}
    # A half that is only a term ("Winter 2027") names no role and must not match anything.
    return {v for v in out if v - _TERM_WORDS and v - {w for w in v if re.fullmatch(r"20\d\d", w)}}


def cities(location: object) -> set:
    found = set()
    for seg in re.split(r"[;/,|]| or ", re.sub(r"\([^)]*\)", " ", str(location or "").lower())):
        seg = re.sub(r"\s+", " ", seg).strip(" -.")
        if len(seg) > 2 and seg not in _PLACE_JUNK and re.search(r"[a-z]", seg):
            found.add(seg)
    return found


def is_repeat(company: str, title: str, location: str, other: dict) -> bool:
    """True when `other` (an application row with company, title, location) is the same role."""
    if not same_company(company_key(company), company_key(other.get("company"))):
        return False
    mine = _variants(title)
    if not (mine & _variants(other.get("title"))):
        return False
    a, b = cities(location), cities(other.get("location"))
    if a and b and not (a & b):
        return False          # a different city is a different requisition
    return True
