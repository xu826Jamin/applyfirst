"""Is a posting still open?

A posting from an employer's own board is dead when it drops off the board (the sweep does
that). A posting that came from somewhere else (Indeed, an alert email, a pasted link) has no
board to disappear from, so its page is read: a 404 or 410 is dead, and so is a page that says
the job is closed, in English, French or German. Anything unclear (a bot wall, a 403, a 429, a
timeout) is "unknown", never dead: a live posting wrongly hidden costs more than a dead one
shown for a day.

The closure phrases and the bot-wall guard are adapted from career-ops, liveness-core.mjs
(MIT License, copyright career-ops contributors).
"""
from __future__ import annotations

import re
import unicodedata

from .net import FetchError, Http

_QUOTES = str.maketrans({"‘": "'", "’": "'", "ʼ": "'", "′": "'", "´": "'", "`": "'",
                         "“": '"', "”": '"', "″": '"'})


def normalise(text: str) -> str:
    """Quotes folded, accents removed, whitespace squeezed, so patterns are plain ASCII."""
    if not isinstance(text, str):
        return ""
    s = unicodedata.normalize("NFD", text.translate(_QUOTES))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def _c(p: str) -> re.Pattern:
    return re.compile(p, re.I)


HARD_EXPIRED = [
    _c(r"job (is )?no longer available"),
    _c(r"job.*no longer open"),
    _c(r"this job has expired"),
    _c(r"job posting has expired"),
    _c(r"no longer accepting applications"),
    _c(r"this (position|role|job) (is )?no longer"),
    _c(r"this (?:job|role|position)(?: listing)? is closed\b(?!-)"),   # not "closed-loop"
    _c(r"job (listing )?not found"),
    _c(r"the page you are looking for doesn.t exist"),
    _c(r"applications?\s+(?:(?:have|are|is)\s+)?closed"),
    _c(r"closed on \d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"),
    _c(r"closed on (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}"),
    _c(r"position has been filled"),
    _c(r"diese stelle (ist )?(nicht mehr|bereits) besetzt"),
    _c(r"offre (expiree|n'est plus disponible)"),
    _c(r"(cette )?offre n'est plus (disponible|en ligne|active)"),
    _c(r"(offre|poste|annonce) (deja )?pourvu(e)?"),
    _c(r"offre (cloturee|desactivee|terminee)"),
    _c(r"ce poste n'est plus (disponible|a pourvoir|ouvert)"),
    _c(r"recrutement (termine|cloture)"),
    _c(r"candidatures (closes|cloturees)"),
]
SOFT_EXPIRED = [_c(r"\bjob expired\b")]
LISTING_PAGE = [_c(r"\d+\s+jobs?\s+found"), _c(r"search for jobs page is loaded")]
BOT_WALL = [
    _c(r"just a moment"), _c(r"performing security verification"), _c(r"checking your browser before"),
    _c(r"verify you are (a |not a )?human"), _c(r"enable javascript and cookies to continue"),
    _c(r"attention required.*cloudflare"), _c(r"\bray id\b"), _c(r"\bcf-ray\b"),
    _c(r"please complete the security check"),
]
_FILLED = _c(r"has been filled\b(?!\s+out)")
_JOB_NOUN = _c(r"\b(?:job|jobs|position|role|posting|opening|vacancy|requisition|req|listing)\b")


def _filled(text: str) -> bool:
    """"the job you applied for has been filled" is closed; "the application form has been
    filled out" is not."""
    for m in _FILLED.finditer(text):
        before = text[max(0, m.start() - 60):m.start()]
        if not _JOB_NOUN.search(before):
            continue
        if re.search(r"\b(?:application|form)\s+$", before, re.I):
            continue
        return True
    return False


def body_signal(body: str) -> tuple[str | None, str | None]:
    """('expired'|'uncertain'|None, short code) for the text of a page that loaded."""
    text = normalise(body)
    if any(p.search(text) for p in BOT_WALL):
        return "uncertain", "bot-wall"
    if any(p.search(text) for p in HARD_EXPIRED) or _filled(text):
        return "expired", "closed-text"
    if any(p.search(text) for p in SOFT_EXPIRED):
        return "expired", "closed-text-soft"
    if any(p.search(text) for p in LISTING_PAGE):
        return "expired", "listing-page"
    return None, None


def check_url(http: Http, url: str) -> str:
    """'live', 'dead' or 'unknown' for one posting URL."""
    try:
        final, body = http.final_url(url)
    except FetchError as e:
        return "dead" if e.status in (404, 410) else "unknown"
    signal, _ = body_signal(body)
    if signal == "expired":
        return "dead"
    if signal == "uncertain":
        return "unknown"
    return "live"
