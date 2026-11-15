"""Small text helpers shared by the filters: whole-phrase matching, sentences, dates."""
from __future__ import annotations

import datetime as dt
import functools
import re
import unicodedata


def fold(s: object) -> str:
    """Lower-case and strip accents, so 'Montréal' and 'montreal' compare equal."""
    s = unicodedata.normalize("NFKD", "" if s is None else str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


@functools.lru_cache(maxsize=4096)
def phrase_re(phrase: str) -> re.Pattern:
    """A whole-word match for a user-typed word or phrase ('java' does not hit 'javascript').
    A space in the phrase also matches a hyphen, so 'co op' finds 'co-op'."""
    esc = re.escape(phrase.strip()).replace(r"\ ", r"[\s\-]+")
    pre = r"(?<![A-Za-z0-9])" if phrase.strip()[:1].isalnum() else ""
    post = r"(?![A-Za-z0-9])" if phrase.strip()[-1:].isalnum() else ""
    return re.compile(pre + esc + post, re.I)


def has_phrase(text: str, phrase: str) -> bool:
    return bool(phrase and phrase.strip() and phrase_re(phrase).search(text or ""))


def real_sentence_break(text: str, i: int) -> bool:
    """True if the '.' at index i ends a sentence rather than sitting inside 'Ph.D.' or
    'e.g.,': those are followed by no space, or by a space and a lowercase letter."""
    if i + 1 >= len(text):
        return True
    if text[i + 1] not in " \n\t":
        return False
    j = i + 1
    while j < len(text) and text[j] in " \n\t":
        j += 1
    nxt = text[j:j + 1]
    return not (nxt.isalpha() and nxt.islower())


def sentences(text: str) -> list[str]:
    """Lines first (job posts are bullet lists with no full stops), then real sentence ends."""
    out: list[str] = []
    for line in (text or "").splitlines():
        start = 0
        i = line.find(".")
        while i != -1:
            if real_sentence_break(line, i):
                out.append(line[start:i + 1])
                start = i + 1
            i = line.find(".", i + 1)
        if start < len(line):
            out.append(line[start:])
    return [s for s in out if s.strip()]


def parse_dt(value: object) -> dt.datetime | None:
    """An ISO date or timestamp as an aware UTC datetime, or None when it cannot be read."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        d = value
    elif isinstance(value, dt.date):
        d = dt.datetime(value.year, value.month, value.day)
    else:
        s = str(value).strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        try:
            d = dt.datetime.fromisoformat(s)
        except ValueError:
            try:
                d = dt.datetime.fromisoformat(s[:10])
            except ValueError:
                return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def parse_date(value: object) -> dt.date | None:
    """The date part of an ISO value (a dict as the old pipeline stored it is accepted)."""
    if isinstance(value, dict):
        value = value.get("date")
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def clip(s: object, n: int = 60) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "..."


def join_words(items: list[str]) -> str:
    items = [str(i) for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]
