"""Small pure helpers shared by the fetchers and the sweep."""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone


def strip_html(raw: str | None) -> str:
    """HTML (possibly entity-escaped, as Greenhouse sends it) to plain text."""
    if not raw:
        return ""
    text = html.unescape(str(raw))
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"</(p|div|li|ul|ol|h\d|tr|br)\s*>|<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


_REL_RE = re.compile(r"posted\s+(\d+)\s*\+?\s*(day|days|hour|hours|week|weeks|month|months)\s+ago", re.I)


def parse_posted(value, now: datetime | None = None) -> str:
    """A source's posting date in any common shape to an ISO timestamp, or '' if unknown.

    Accepts ISO strings, epoch seconds or milliseconds, plain dates, and Workday's relative
    "Posted 3 Days Ago". "Posted 30+ Days Ago" is a lower bound, not a date, so it stays ''."""
    if value is None or value == "":
        return ""
    now = now or datetime.now(timezone.utc)
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,14}", value.strip())):
        n = float(value)
        if n > 1e11:       # milliseconds
            n /= 1000.0
        if n < 1e8:
            return ""
        return iso(datetime.fromtimestamp(n, tz=timezone.utc))
    s = str(value).strip()
    low = s.lower()
    if low in ("posted today", "today"):
        return iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
    if low in ("posted yesterday", "yesterday"):
        return iso((now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
    m = _REL_RE.search(s)
    if m:
        if "+" in s:
            return ""
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = {"day": timedelta(days=n), "hour": timedelta(hours=n),
                 "week": timedelta(weeks=n), "month": timedelta(days=30 * n)}[unit.rstrip("s")]
        base = now - delta
        if unit.startswith("day") or unit.startswith("week") or unit.startswith("month"):
            base = base.replace(hour=0, minute=0, second=0, microsecond=0)
        return iso(base)
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return iso(d)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            d = datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return iso(d)
        except ValueError:
            continue
    return ""


_AGE_RE = re.compile(r"(\d+)\s*(\+)?\s*(h|hr|hrs|hours?|d|days?|w|wks?|weeks?|mo|months?)\b", re.I)


def parse_age_text(text: str, now: datetime | None = None) -> str:
    """Job-site ages ("24h", "2d", "Posted 3 days ago", "Just posted") to an ISO timestamp.
    "30+ days" is a lower bound, so it stays ''."""
    s = (text or "").strip().lower()
    if not s:
        return ""
    now = now or datetime.now(timezone.utc)
    if re.search(r"just posted|posted today|^today|^new$|active today", s):
        return iso(now)
    m = _AGE_RE.search(s)
    if not m or m.group(2):
        return ""
    n, unit = int(m.group(1)), m.group(3).lower()
    if unit.startswith("h"):
        return iso(now - timedelta(hours=n))
    days = n if unit.startswith("d") else 7 * n if unit.startswith("w") else 30 * n
    return iso((now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0))


def parse_deadline(value) -> str:
    """An application deadline as YYYY-MM-DD, or ''."""
    iso_ts = parse_posted(value)
    return iso_ts[:10] if iso_ts else ""


# --------------------------------------------------------------------------- identity

_LEGAL_SUFFIXES = {"inc", "incorporated", "ltd", "limited", "llc", "lp", "corp", "corporation",
                   "co", "company", "canada", "gmbh", "plc", "usa", "us"}


def company_key(name: str) -> str:
    """"Remarcable, Inc." and "Remarcable" are one company."""
    words = re.sub(r"[^\w]+", " ", (name or "").lower()).split()
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def _norm_title(t: str) -> str:
    return re.sub(r"[^\w]+", " ", (t or "").lower()).strip()


def title_variants(title: str) -> set[str]:
    """The normalised title plus each half of a bilingual title.

    "Stagiaire en developpement logiciel / Software Developer Intern" is one posting written
    twice. Only a slash or pipe with spaces around it splits; a hyphen or comma does not,
    because "Engineer - Infrastructure" and "Engineer - Frontend" are different roles. A
    parenthesised term such as "(Winter 2027, 8 Months)" stays inside its title: two terms of
    one role are two postings."""
    parts = re.split(r"\s[/|]\s", title or "")
    return {v for v in [_norm_title(title)] + [_norm_title(p) for p in parts] if v}


def normalise_url(url: str) -> str:
    """One posting, one string. Scheme, www., a trailing slash and a fragment are noise; the
    query string is NOT, because some boards (Greenhouse-embedded sites, Indeed's ?jk=) carry
    the identity there and stripping it would merge every posting on the board into one."""
    u = (url or "").strip().split("#", 1)[0]
    u = re.sub(r"(?i)^https?://", "", u)
    u = re.sub(r"(?i)^www\.", "", u)
    u = u.rstrip("/").lower()
    for tail in ("/application", "/apply"):
        if u.endswith(tail):
            u = u[: -len(tail)]
    return u


def today_utc() -> date:
    return datetime.now(timezone.utc).date()
