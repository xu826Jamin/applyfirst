"""Telling one posting from the same posting seen twice.

The same job shows up on a company's own board, on Indeed and on Glassdoor, and big employers
post one role once per site. Two postings are one when they match on company, title and country,
or when their descriptions are nearly identical (a 64-bit SimHash over three-word shingles).

The fingerprint approach follows career-ops's jd_fingerprint (MIT License, copyright career-ops
contributors); this version uses only the standard library, so its hashes are not bit-identical.
"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata

from .util import company_key, normalise_url, title_variants

MIN_CHARS = 200            # a shorter text is too thin to say anything about identity
MIN_TOKENS = 3
THRESHOLD = 0.92
SHINGLE = 3

_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalise_text(text: str) -> str:
    t = html.unescape(text or "")
    t = _TAG.sub(" ", t)
    t = _URL.sub(" ", t)
    t = unicodedata.normalize("NFKD", t).lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", t).strip()


def fingerprint_text(text: str) -> str:
    """16 hex digits, or '' when the text is too thin to fingerprint."""
    norm = normalise_text(text)
    tokens = norm.split()
    if len(norm) < MIN_CHARS or len(tokens) < MIN_TOKENS:
        return ""
    weights = [0] * 64
    for i in range(max(len(tokens) - SHINGLE + 1, 1)):
        shingle = " ".join(tokens[i:i + SHINGLE])
        h = int.from_bytes(hashlib.sha1(shingle.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            weights[bit] += 1 if (h >> bit) & 1 else -1
    value = 0
    for bit in range(64):
        if weights[bit] > 0:
            value |= 1 << bit
    return f"{value:016x}"


def similarity(a: str, b: str) -> float:
    """1 minus the share of the 64 bits that differ. 0.0 when either is missing."""
    if not a or not b:
        return 0.0
    return 1.0 - bin(int(a, 16) ^ int(b, 16)).count("1") / 64.0


def _kind_rank(source: str) -> int:
    """Which copy to keep: the employer's own board beats an aggregator's copy."""
    return 1 if source in ("indeed", "glassdoor", "linkedin", "google", "email", "manual") else 0


def find_duplicates(rows: list[dict]) -> dict[str, str]:
    """{posting id: id of the posting it duplicates} for a set of rows.

    Each row needs id, source, company, title, country, url, first_seen_at, fingerprint. The
    canonical copy of a group is the employer-board one, then the earliest seen. A row is a
    duplicate when it has the same url, or the same company and title and a compatible country,
    or the same company and country and a near-identical description."""
    # A posting the user already acted on stays canonical, whatever else shows up.
    ordered = sorted(rows, key=lambda r: (0 if r.get("user_action") else 1, _kind_rank(r.get("source") or ""),
                                          r.get("first_seen_at") or "", r["id"]))
    canon_by_url: dict[str, str] = {}
    canon_by_role: dict[tuple, str] = {}
    canon_prints: dict[tuple, list[tuple[str, str]]] = {}
    out: dict[str, str] = {}
    for r in ordered:
        company = company_key(r.get("company") or "")
        country = r.get("country") or ""
        url = normalise_url(r.get("url") or "")
        hit = canon_by_url.get(url) if url else None
        if not hit and company:
            for t in title_variants(r.get("title") or ""):
                for c in {country, ""} if country else {""}:
                    hit = hit or canon_by_role.get((company, t, c))
                if not country:
                    # unknown country: it may be the same role as any country's copy
                    hit = hit or next((v for (co, ti, _c), v in canon_by_role.items()
                                       if co == company and ti == t), None)
        fp = r.get("fingerprint") or ""
        if not hit and company and fp:
            for pid, other in canon_prints.get((company, country), []):
                if similarity(fp, other) >= THRESHOLD:
                    hit = pid
                    break
        if hit and hit != r["id"]:
            out[r["id"]] = hit
            continue
        if url:
            canon_by_url[url] = r["id"]
        if company:
            for t in title_variants(r.get("title") or ""):
                canon_by_role.setdefault((company, t, country), r["id"])
            if fp:
                canon_prints.setdefault((company, country), []).append((r["id"], fp))
    return out
