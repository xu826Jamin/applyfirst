"""Career level: internship, co-op, new-grad, entry, mid, senior.

Ported from the private pipeline's submit_gate (level words, the 'a student marker in the
title always wins' rule, the guarded senior-word reader), score_jobs (INTERN_RE including
'fellow', years-of-experience penalty with its student-posting suppression) and
source_jobs (analyst cohort programs).

Calibration rules carried over:
  * A student marker in the TITLE always wins ("Junior Software Developer Co-op" is a co-op).
  * A description that names interns is never guessed senior from a stray "senior engineer".
  * Years of experience asked for on a student-titled posting are ignored (campus postings
    disclaim them: "as a full-time employee we would require 3-5 years, however ...").
  * No signal at all gives no level (an unmarked posting), never a guessed one.
"""
from __future__ import annotations

import json
import re

from .text import clip

LEVEL_ORDER = ["internship", "co-op", "new-grad", "entry", "mid", "senior"]
LEVEL_LABEL = {
    "internship": "an internship",
    "co-op": "a co-op",
    "new-grad": "a new-grad role",
    "entry": "an entry-level role",
    "mid": "a mid-level role",
    "senior": "a senior role",
}

# --------------------------------------------------------------------------- title markers

_COOP = re.compile(
    r"\bco[\s\-]?ops?\b|\bwork[\s\-]terms?\b|\bprofessional\s+(?:experience|engineering)\s+year\b|"
    r"\bPEY\b|\balternance\b", re.I)
# 'fellow' is here on purpose: 18 of 20 live "fellow" titles were early-career programs.
_INTERN = re.compile(
    r"\b(?:interns?|internships?|stagiaires?|placements?|apprentices?|apprenticeships?|"
    r"fellows?|fellowships?|students?|campus|[eé]tudiant(?:e)?s?|working\s+student)\b|"
    r"^\s*stage\b|\bstage\s+(?:en|de|d')|"
    # bank-style cohort programs: "Summer Analyst", "Campus Analyst", "Analyst Program 2027"
    r"\b(?:summer|winter|fall|spring|campus)\s+(?:\S+\s+){0,2}analyst\b|"
    r"\banalyst\s+program\b.{0,30}?\b20\d\d\b|\b20\d\d\b.{0,30}?\banalyst\s+program\b", re.I)
# "Summer 2027" in a title with no other marker is a student term ("Software Developer, Summer
# 2027"); next to "Co-op" it only says which term, so it must not add a second level.
_SEASON_YEAR = re.compile(r"\b(?:summer|winter|fall|spring)\s+20\d\d\b", re.I)
_NEWGRAD = re.compile(
    r"\bnew[\s\-]*grad(?:uate)?s?\b|"
    r"\bgraduate\s+(?:program(?:me)?|scheme|engineer|developer|software|analyst|associate|"
    r"trainee|role|position)\b|\buniversity\s+grad(?:uate)?s?\b|\brecent\s+grad(?:uate)?s?\b|"
    r"\bearly[\s\-]*careers?\b|\bcampus\s+hire\b|\bclass\s+of\s+20\d\d\b|\bgrad\s+(?:program|role)\b",
    re.I)
_ENTRY = re.compile(
    r"\bjunior\b|\bjr\b\.?|\bassociate\b(?!\s+(?:director|vice|vp|principal|partner|professor))|"
    r"\bentry[\s\-]*level\b|\b(?:engineer|developer|analyst|programmer|scientist|designer|"
    r"specialist)\s+(?-i:I|1)\b(?![\w.\-]*\d)", re.I)
_MID = re.compile(
    r"\bintermediate\b|\bmid[\s\-]?level\b|\bmid[\s\-]?career\b|"
    r"\b(?:engineer|developer|analyst|programmer|scientist|designer|specialist)\s+(?-i:II|III|2|3)\b|"
    r"\bmanager\b", re.I)
_SENIOR_WORDS = ("senior", "sr", "staff", "principal", "lead", "director", "head of", "vp",
                 "vice president", "chief", "distinguished")
_SENIOR_RE = re.compile(
    r"(?:^|[^a-z0-9])(" + "|".join(re.escape(w) for w in _SENIOR_WORDS) + r")(?=$|[^a-z0-9])", re.I)
_SENIOR_NUM = re.compile(r"\b(?:engineer|developer|analyst|scientist)\s+(?-i:IV|V|4|5)\b", re.I)
# Words that follow a level word without being a level: "principal responsibilities",
# "lead the", "mid-market", "lead generation".
_NOT_LEVEL_AFTER = {
    "principal": {"responsibilities", "responsibility", "duties", "accountabilities",
                  "objectives", "purpose", "tasks", "activities"},
    "lead": {"to", "the", "a", "an", "our", "and", "or", "by", "on", "in", "for", "with",
             "from", "mentoring", "projects", "generation", "gen", "qualification"},
    "head": {"count"},
}


def _senior_in_title(title: str) -> bool:
    low = title.lower()
    for m in _SENIOR_RE.finditer(low):
        word = m.group(1).lower()
        after = re.match(r"^[^a-z0-9]*([a-z0-9-]+)", low[m.end(1):])
        if after and after.group(1) in _NOT_LEVEL_AFTER.get(word, ()):
            continue
        return True
    return bool(_SENIOR_NUM.search(title))


def title_levels(title: str) -> list[str]:
    """Levels the title names. A student or new-grad marker wins over any other word."""
    title = title or ""
    out: list[str] = []
    if _COOP.search(title):
        out.append("co-op")
    if _INTERN.search(title):
        out.append("internship")
    if _NEWGRAD.search(title):
        out.append("new-grad")
    if not out and _SEASON_YEAR.search(title):
        out.append("internship")
    if out:
        return [lv for lv in LEVEL_ORDER if lv in out]
    if _senior_in_title(title):
        return ["senior"]
    if _ENTRY.search(title):
        return ["entry"]
    if _MID.search(title):
        return ["mid"]
    return []


# --------------------------------------------------------------------------- description

_D_COOP = re.compile(r"\bco[\s\-]?ops?\b|\bwork[\s\-]terms?\b", re.I)
_D_INTERN = re.compile(
    r"\binterns?\b|\binternships?\b|\bstagiaires?\b|\bplacement\s+(?:year|student|program)\b", re.I)
_D_NEWGRAD = re.compile(
    r"\bnew[\s\-]*grad(?:uate)?s?\b|\bgraduate\s+(?:program(?:me)?|scheme)\b|"
    r"\bearly[\s\-]*careers?\b|\buniversity\s+grad", re.I)
_STRUCT_KEYS = ("employment_type", "employmenttype", "commitment", "job_type", "jobtype",
                "type", "term", "worker_type", "workertype", "time_type")


def _student_in_text(text: str) -> list[str]:
    """Levels a description names. One passing mention deep in the text is not enough: it needs
    two mentions, or one in the opening lines."""
    out: list[str] = []
    head = text[:500]
    for lv, rx in (("co-op", _D_COOP), ("internship", _D_INTERN), ("new-grad", _D_NEWGRAD)):
        hits = rx.findall(text)
        if len(hits) >= 2 or (hits and rx.search(head)):
            out.append(lv)
    return out


def structured_text(raw: object) -> str:
    """The employment-type style fields from the source's raw JSON (Lever's commitment,
    Greenhouse metadata and so on). Plain 'Full-time' is not evidence of anything."""
    if not raw:
        return ""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return ""
    found: list[str] = []

    def walk(o: object, depth: int = 0) -> None:
        if depth > 3:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).lower().replace("-", "_") in _STRUCT_KEYS and isinstance(v, (str, list)):
                    found.append(" ".join(map(str, v)) if isinstance(v, list) else v)
                elif isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o[:20]:
                walk(v, depth + 1)

    walk(data)
    return " ".join(found)


# --------------------------------------------------------------------------- years of experience

_YEARS = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)\b",
    re.I)
_NOT_YEARS_BEFORE = re.compile(r"\b(past|last|previous|within|next|over\s+the|after|every|each)\s*$", re.I)
_YEARS_OPTIONAL = re.compile(r"preferred|nice\s+to\s+have|an\s+asset|a\s+plus|bonus|ideally", re.I)
_DISCLAIMER = re.compile(
    r"(however|as part of|campus program|for (?:a )?full[\s-]time|full[\s-]time employee|"
    r"not required for|does not apply|we (?:do not|don't) (?:require|expect))", re.I)
_DISCLAIMER_WINDOW = 250


def suppression_reason(match: re.Match, text: str, title: str) -> str:
    """Why a years-of-experience match should NOT count, or '' when it should. Kept tight on
    purpose: a wrongly suppressed requirement promotes a posting the user cannot get."""
    if title_levels(title) and set(title_levels(title)) & {"internship", "co-op", "new-grad"}:
        return "student-shaped title"
    window = text[max(0, match.start() - _DISCLAIMER_WINDOW):match.end() + _DISCLAIMER_WINDOW]
    m = _DISCLAIMER.search(window)
    return f"disclaimer near match: {m.group(0)!r}" if m else ""


def years_required(title: str, description: str) -> int | None:
    """The largest minimum years of experience the posting really asks for, or None."""
    text = description or ""
    best: int | None = None
    for m in _YEARS.finditer(text):
        n = int(m.group(1))
        if n < 1 or n > 25:
            continue
        if _NOT_YEARS_BEFORE.search(text[max(0, m.start() - 20):m.start()]):
            continue
        around = text[max(0, m.start() - 100):m.end() + 100]
        if not re.search(r"experience|\bexp\b|expérience", around, re.I):
            continue
        if _YEARS_OPTIONAL.search(text[m.end():m.end() + 50]):
            continue
        if suppression_reason(m, text, title):
            continue
        best = n if best is None else max(best, n)
    return best


# --------------------------------------------------------------------------- the detector


def detect_levels(title: str, description: str = "", raw: object = None) -> list[str]:
    """Every level the posting fits, in LEVEL_ORDER; [] when nothing in it says."""
    title, description = title or "", description or ""
    from_title = title_levels(title)
    if from_title:
        return from_title
    struct = structured_text(raw)
    if struct:
        found = [lv for lv, rx in (("co-op", _COOP), ("internship", _INTERN),
                                    ("new-grad", _NEWGRAD)) if rx.search(struct)]
        if found:
            return [lv for lv in LEVEL_ORDER if lv in found]
        if _ENTRY.search(struct):
            return ["entry"]
    yrs = years_required(title, description)
    student = _student_in_text(description)
    if student and (yrs is None or yrs < 3):
        return [lv for lv in LEVEL_ORDER if lv in student]
    if yrs is not None:
        if yrs >= 7:
            return ["senior"]
        if yrs >= 3:
            return ["mid"]
        return ["entry"]
    return []


def primary(levels: list[str]) -> str:
    for lv in LEVEL_ORDER:
        if lv in levels:
            return lv
    return ""


def label(levels: list[str]) -> str:
    return LEVEL_LABEL.get(primary(levels), "")


def show(title: str) -> str:
    return clip(title, 50)
