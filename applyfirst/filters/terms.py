"""What a posting says about timing, length, language, eligibility and who may apply.

Ported from an earlier version's score_jobs.py (term_months, extract_deadline with its
start/end/open/assessment-date guard, french_flag generalized to any language,
SCHOOL_RESTRICTION_RE) and submit_gate.py (closed text, US-citizen phrases).

Calibration rules carried over:
  * A posting that states no term length is kept: silence is not a short term.
  * "Have you interviewed with us in the past 12 months?" and "within 6 months of graduation"
    are not work terms. Both ends of "8-12 month" are options.
  * A deadline is the first date AFTER the deadline phrase, skipping dates labelled start, end,
    open, assessment, interview, posted. A yearless date gets an inferred year and is never used
    as proof a posting closed. A date already past is never "soonest" in the queue.
  * A language that is only "preferred", "an asset" or "a plus" is not a requirement. The
    nearest marker to the language word decides, so "English is required and French is an asset"
    reads French as an asset.
  * A school named in a posting is a note for the user, never a reason to hide the posting: the
    form often accepts other schools.
"""
from __future__ import annotations

import datetime as dt
import re

from .text import fold, parse_date, sentences

# --------------------------------------------------------------------------- term length

_TERM_RANGE = re.compile(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*[-–]?\s*months?\b", re.I)
_TERM_LIST = re.compile(
    r"\b((?:\d{1,2}\s*(?:/|,|or|and)\s*)+\d{1,2})\s*[-–]?\s*months?\b", re.I)
_TERM_ONE = re.compile(r"\b(\d{1,2})\s*[-–]?\s*months?\b", re.I)
_YEAR_LONG = re.compile(
    r"\b(?:year[\s-]?long|(?:one|1)[\s-]year)\s+(?:internship|co-?op|placement|term|contract|"
    r"program(?:me)?|work\s+term)\b", re.I)
_NOT_A_TERM = re.compile(
    r"\b(past|last|next|previous|within|coming|first|after|every|each|over|than|per|"
    r"at\s+least)\s*$", re.I)
_NOT_A_TERM_AFTER = re.compile(
    r"^\s*(?:or\s+more\s+)?(?:of\s+)?(?:\w+\s+){0,3}?(?:experience|exp\b|old\b|notice|"
    r"probation|warranty|ago|prior)", re.I)


def term_months(*texts: str) -> list[int]:
    """Distinct work-term lengths named, in months. Empty when the posting is silent."""
    out: set[int] = set()

    def ok(n: int, body: str, start: int, end: int) -> bool:
        if not 2 <= n <= 24:
            return False
        if _NOT_A_TERM.search(body[max(0, start - 20):start]):
            return False
        if _NOT_A_TERM_AFTER.search(body[end:end + 45]):
            return False
        return True

    for text in texts:
        body = text or ""
        used: list[tuple[int, int]] = []
        for m in _TERM_RANGE.finditer(body):
            if ok(int(m.group(2)), body, m.start(), m.end()):
                for g in (1, 2):
                    if 2 <= int(m.group(g)) <= 24:
                        out.add(int(m.group(g)))
                used.append((m.start(), m.end()))
        for m in _TERM_LIST.finditer(body):
            if any(s <= m.start() < e for s, e in used):
                continue
            nums = [int(x) for x in re.findall(r"\d{1,2}", m.group(1))]
            if all(2 <= n <= 24 for n in nums) and ok(nums[-1], body, m.start(), m.end()):
                out.update(nums)
                used.append((m.start(), m.end()))
        for m in _TERM_ONE.finditer(body):
            if any(s <= m.start() < e for s, e in used):
                continue
            if ok(int(m.group(1)), body, m.start(), m.end()):
                out.add(int(m.group(1)))
        if _YEAR_LONG.search(body):
            out.add(12)
    return sorted(out)


# --------------------------------------------------------------------------- start terms

_SEASON_MONTHS = {"winter": {1, 2}, "spring": {3, 4, 5}, "summer": {5, 6, 7}, "fall": {8, 9, 10},
                  "autumn": {8, 9, 10}, "hiver": {1, 2}, "printemps": {3, 4, 5},
                  "ete": {5, 6, 7}, "automne": {8, 9, 10}}
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_SEASON_NAMES = "winter|spring|summer|fall|autumn|hiver|printemps|[eé]t[eé]|automne"
_SEASON_YEAR = re.compile(
    rf"\b({_SEASON_NAMES})\s*(?:term\s*|semester\s*|session\s*)?(?:of\s*)?(?:['’]\s*)?(20\d\d)\b|"
    rf"\b(20\d\d)\s+({_SEASON_NAMES})\b", re.I)
_MONTH_YEAR = re.compile(rf"\b({_MONTH_NAMES})\.?\s*,?\s*(?:of\s+)?(20\d\d)\b", re.I)
_ISO_MONTH = re.compile(r"\b(20\d\d)-(0[1-9]|1[0-2])(?:-\d\d)?\b")
_START_CONTEXT = re.compile(
    r"start|begin|commenc|term\b|internship|co-?op|placement|position|role|cohort|session|"
    r"semester|available|work\s+term", re.I)
_NOT_START_CONTEXT = re.compile(
    r"graduat|class\s+of|posted|deadline|clos(?:e|es|ing)|applications?\s+(?:open|due)|"
    r"apply\s+by|expires?|copyright|updated|interview|assessment|offers?\s+(?:will|are)", re.I)


def _season_months(name: str) -> set[int]:
    return _SEASON_MONTHS.get(fold(name), set())


def _label(season: str, year: int) -> str:
    return f"{season.capitalize()} {year}"


def _terms_in(text: str, need_context: bool) -> list[tuple[int, set[int], str]]:
    found: list[tuple[int, set[int], str]] = []

    def context_ok(m: re.Match) -> bool:
        if not need_context:
            return True
        win = text[max(0, m.start() - 70):m.end() + 70]
        return bool(_START_CONTEXT.search(win)) and not _NOT_START_CONTEXT.search(win)

    for m in _SEASON_YEAR.finditer(text):
        season, year = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        if context_ok(m):
            found.append((int(year), _season_months(season), _label(fold(season), int(year))))
    for m in _MONTH_YEAR.finditer(text):
        if context_ok(m):
            mo = _MONTHS[m.group(1).lower()]
            found.append((int(m.group(2)), {mo}, f"{m.group(1).capitalize()} {m.group(2)}"))
    for m in _ISO_MONTH.finditer(text):
        if context_ok(m):
            found.append((int(m.group(1)), {int(m.group(2))}, f"{m.group(1)}-{m.group(2)}"))
    return found


def start_terms(title: str, description: str = "") -> list[tuple[int, set[int], str]]:
    """Start terms a posting states, as (year, months, label). The title is authoritative when it
    names one; the description counts only next to words like 'start', 'term' or 'internship'."""
    from_title = _terms_in(title or "", need_context=False)
    if from_title:
        return from_title
    return _terms_in((description or "")[:6000], need_context=True)


def parse_wanted_term(s: str) -> tuple[int, set[int] | None, str] | None:
    """A term the user typed: '2027-05', '2027', 'Summer 2027' or 'May 2027'."""
    s = str(s or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(20\d\d)-(0[1-9]|1[0-2])", s)
    if m:
        return int(m.group(1)), {int(m.group(2))}, s
    m = re.fullmatch(r"(20\d\d)", s)
    if m:
        return int(m.group(1)), None, s
    got = _terms_in(s, need_context=False)
    if got:
        y, months, label = got[0]
        return y, months, s
    return None


def start_term_fits(stated: list[tuple[int, set[int], str]], wanted: list[str]) -> tuple[bool, str]:
    """(fits, plain reason). Fits when nothing is stated or nothing parseable is wanted."""
    parsed = [p for p in (parse_wanted_term(w) for w in wanted) if p]
    if not stated or not parsed:
        return True, ""
    for year, months, _ in stated:
        for wy, wm, _w in parsed:
            if wy == year and (wm is None or (months & wm)):
                return True, ""
    names = ", ".join(dict.fromkeys(label for _, _, label in stated))
    wants = ", ".join(w for _, _, w in parsed)
    return False, f"Starts {names}; you want {wants}"


# --------------------------------------------------------------------------- deadline

DEADLINE_PHRASE_RE = re.compile(
    r"deadline|apply\s+by|applications?\s+close|closing\s+date|must\s+apply\s+before", re.I)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_MDY = re.compile(
    rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*,?\s+(\d{{4}})\b", re.I)
_DATE_DMY = re.compile(
    rf"\b(\d{{1,2}})\s*(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_NAMES})\.?\s*,?\s+(\d{{4}})\b", re.I)
_DATE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_DATE_PATTERNS = (_DATE_ISO, _DATE_MDY, _DATE_DMY, _DATE_SLASH)
_DATE_MD_NOYEAR = re.compile(
    rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})\s*(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{{4}})(?![:/.]\d)", re.I)
_DATE_DM_NOYEAR = re.compile(
    rf"\b(\d{{1,2}})\s*(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_NAMES})\b\.?(?!\s*,?\s*\d{{4}})", re.I)
_WINDOW_BEFORE = 60
_WINDOW_AFTER = 150
# A date labelled as something other than the application deadline (found misread in a real
# store: "Applications Open", "Position End Date", programme dates).
_NOT_DEADLINE_LABEL = re.compile(
    r"\b(start(?:s|ing)?|begin(?:s|ning)?|commenc\w*|end(?:s|ing)?|open(?:s|ed|ing)?(?!\s+until)|"
    r"assessment\w*|interview\w*|posted|outcomes?|offers?|programme|program)\b", re.I)
_RANGE_JOIN = re.compile(r"^\s*(?:to|-|–|—|and|&|until|through)\s*(?:\w+day\s*)?$", re.I)
_BEFORE_PHRASE = re.compile(
    r"^[\s,.;:–-]*(?:(?:is|are|will be|be|the|our|your|final|formal|official|application|"
    r"applications|closing|apply|by|on|date)\s*)*$", re.I)


def _build_date(pat: re.Pattern, m: re.Match) -> str | None:
    try:
        if pat is _DATE_ISO:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif pat is _DATE_MDY:
            mo, d, y = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
        elif pat is _DATE_DMY:
            d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
        else:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return dt.date(y, mo, d).isoformat()
    except (ValueError, KeyError):
        return None


def _candidates(text: str) -> list[tuple[int, int, object, str]]:
    found: list[tuple[int, int, object, str]] = []
    for pat in _DATE_PATTERNS:
        for dm in pat.finditer(text):
            iso = _build_date(pat, dm)
            if iso and 2024 <= int(iso[:4]) <= 2032:
                found.append((dm.start(), dm.end(), iso, "stated"))
    for pat in (_DATE_MD_NOYEAR, _DATE_DM_NOYEAR):
        for dm in pat.finditer(text):
            if any(s <= dm.start() < e for s, e, _, _ in found):
                continue
            if pat is _DATE_MD_NOYEAR:
                mo, d = _MONTHS[dm.group(1).lower()], int(dm.group(2))
            else:
                mo, d = _MONTHS[dm.group(2).lower()], int(dm.group(1))
            if 1 <= d <= 31:
                found.append((dm.start(), dm.end(), (mo, d), "yearless"))
    return sorted(found, key=lambda c: c[0])


def _infer_year(month_day: tuple[int, int], reference: dt.date) -> str | None:
    mo, d = month_day
    best = None
    for y in (reference.year - 1, reference.year, reference.year + 1):
        try:
            cand = dt.date(y, mo, d)
        except ValueError:
            continue
        if best is None or abs((cand - reference).days) < abs((best - reference).days):
            best = cand
    return best.isoformat() if best else None


def _generic_plural(desc: str, m: re.Match) -> bool:
    """'meeting deadlines' is a duty, not an application deadline."""
    if desc[m.end():m.end() + 1].lower() != "s" or m.group(0).lower() != "deadline":
        return False
    return not re.search(r"(application|apply|closing)\s+$", desc[max(0, m.start() - 15):m.start()], re.I)


def extract_deadline(desc: str, reference: dt.date | None = None) -> dict | None:
    """An application deadline named in posting text, or None when no deadline phrase appears.
    Returns {"phrase", "raw", "date", "date_basis"}; date_basis is 'stated', 'inferred-year' or
    None (the phrase was there but no date could be read)."""
    if not desc:
        return None
    matches = list(DEADLINE_PHRASE_RE.finditer(desc))
    if not matches:
        return None
    reference = reference or dt.date.today()
    first_window = first_phrase = None
    for m in matches:
        lo = max(0, m.start() - _WINDOW_BEFORE)
        hi = min(len(desc), m.end() + _WINDOW_AFTER)
        window = desc[lo:hi]
        if first_window is None:
            first_window, first_phrase = window, m.group(0)
        if _generic_plural(desc, m):
            continue
        after = desc[m.end():hi]
        cands = _candidates(after)
        for i, (s, e, val, basis) in enumerate(cands):
            if _NOT_DEADLINE_LABEL.search(after[:s]):
                break
            if basis == "stated" and s <= _WINDOW_AFTER:
                return {"phrase": m.group(0), "raw": re.sub(r"\s+", " ", window).strip(),
                        "date": val, "date_basis": "stated"}
            if basis == "yearless" and s <= 60:
                for s2, e2, val2, basis2 in cands[i + 1:]:   # "from August 20 to August 26, 2026"
                    if basis2 == "stated" and s2 - e <= 40 and _RANGE_JOIN.match(after[e:s2]):
                        return {"phrase": m.group(0), "raw": re.sub(r"\s+", " ", window).strip(),
                                "date": val2, "date_basis": "stated"}
                    break
                return {"phrase": m.group(0), "raw": re.sub(r"\s+", " ", window).strip(),
                        "date": _infer_year(val, reference), "date_basis": "inferred-year"}
        before = desc[max(0, m.start() - 70):m.start()]
        for s, e, val, basis in reversed(_candidates(before)):
            if (basis == "stated" and _BEFORE_PHRASE.match(before[e:])
                    and not _NOT_DEADLINE_LABEL.search(before[max(0, s - 25):s])):
                return {"phrase": m.group(0), "raw": re.sub(r"\s+", " ", window).strip(),
                        "date": val, "date_basis": "stated"}
            break
    return {"phrase": first_phrase, "raw": re.sub(r"\s+", " ", first_window or "").strip(),
            "date": None, "date_basis": None}


def stated_deadline(posting: dict, reference: dt.date | None = None) -> str:
    """The posting's deadline as an ISO date: the source's own field first, then a date the
    description states with a year. A yearless guess is never returned."""
    own = parse_date(posting.get("deadline"))
    if own:
        return own.isoformat()
    found = extract_deadline(posting.get("description") or "", reference)
    if found and found.get("date") and found.get("date_basis") == "stated":
        return found["date"]
    return ""


_CLOSED_TEXT = re.compile(
    r"\b(?:no\s+longer\s+(?:accepting|taking|available|open)|applications?\s+(?:are\s+|is\s+)?"
    r"(?:now\s+)?closed|(?:position|job|role|posting|requisition)\s+(?:has\s+been\s+|is\s+|was\s+)?"
    r"(?:filled|closed|expired|removed)|this\s+job\s+has\s+expired|deadline\s+has\s+passed|"
    r"we\s+are\s+not\s+accepting\s+applications)\b", re.I)


def closed_phrase(text: str) -> str:
    m = _CLOSED_TEXT.search(text or "")
    return m.group(0) if m else ""


# --------------------------------------------------------------------------- language

# name -> words that mention it. Anything not listed is matched by its own name.
LANGUAGE_WORDS = {
    "french": ["french", "fran[cç]ais", "francais"],
    "spanish": ["spanish", "espa[nñ]ol", "espanol", "castellano"],
    "german": ["german", "deutsch"],
    "mandarin": ["mandarin", "chinese", "putonghua"],
    "cantonese": ["cantonese"],
    "japanese": ["japanese"],
    "korean": ["korean"],
    "portuguese": ["portuguese", "portugu[eê]s"],
    "italian": ["italian", "italiano"],
    "hindi": ["hindi"],
    "arabic": ["arabic"],
    "russian": ["russian"],
    "dutch": ["dutch", "nederlands"],
    "polish": ["polish"],
    "turkish": ["turkish"],
    "hebrew": ["hebrew"],
    "vietnamese": ["vietnamese"],
    "tagalog": ["tagalog", "filipino"],
    "punjabi": ["punjabi"],
    "urdu": ["urdu"],
    "swedish": ["swedish"],
}
_ALL_LANG_RE = re.compile(
    r"\b(?:" + "|".join(w for ws in LANGUAGE_WORDS.values() for w in ws) + r")\b", re.I)
_BILINGUAL = re.compile(r"\bbilingual(?:ism)?\b|\bbilingue\b", re.I)
_REQ_MARK = re.compile(
    r"is\s+required|are\s+required|required\b|requirement|\bmust\b|mandatory|essential|"
    r"obligatoire|exig\w+|fluent|fluency|proficien\w+|native\s+(?:level|speaker)|ma[iî]trise|"
    r"able\s+to\s+(?:speak|communicate|read|write)|speak(?:s|ing)?\b|communicat\w+\s+(?:in|with)|"
    r"written\s+and\s+(?:verbal|spoken)|working\s+knowledge", re.I)
_ASSET_MARK = re.compile(
    r"\basset\b|atout|\bpreferred\b|\bprefer\w*|\ba\s+plus\b|\bplus\b|nice\s+to\s+have|\bbonus\b|"
    r"\badvantage\b|beneficial|not\s+(?:required|necessary|mandatory)|optional|desirable|"
    r"would\s+be\s+(?:great|nice|helpful)", re.I)
_MARK_DISTANCE = 90

_STOPWORDS = {
    "french": re.compile(
        r"\b(le|la|les|des|une|dans|pour|avec|vous|nous|est|sont|aux|du|au|par|sur|qui|"
        r"que|plus|votre|notre|ainsi|afin)\b", re.I),
    "spanish": re.compile(
        r"\b(el|los|las|una|con|para|por|que|del|nuestro|usted|somos|est[aá]|y|en|de)\b", re.I),
    "german": re.compile(
        r"\b(der|die|das|und|f[uü]r|mit|sie|wir|ist|sind|ein|eine|von|auf|bei|zu)\b", re.I),
}
_EN_STOPWORDS = re.compile(
    r"\b(the|and|of|to|in|for|with|you|we|is|are|on|as|by|that|will|your|our|from|at)\b", re.I)


def _lang_regex(language: str) -> re.Pattern:
    key = fold(language).strip()
    words = LANGUAGE_WORDS.get(key) or [re.escape(key)]
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I)


def posting_written_only_in(text: str, language: str, floor: int = 50) -> bool:
    """True when the text is in `language` with no English version beside it."""
    key = fold(language).strip()
    sw = _STOPWORDS.get(key)
    if sw is None:
        return False
    other = len(sw.findall(text or ""))
    en = len(_EN_STOPWORDS.findall(text or ""))
    return other >= floor and en < floor


def language_flag(text: str, language: str, title: str = "") -> str:
    """'required', 'asset' or '' for the strongest mention of `language` in `text`. Scoped to
    the sentence holding the mention; the nearest requirement-or-asset word to the mention wins."""
    rx = _lang_regex(language)
    is_french = fold(language).strip() == "french"
    strongest = ""
    # The title: "Bilingual Support Intern" or "French-speaking Developer" reads as a requirement.
    if title and (rx.search(title) or (is_french and _BILINGUAL.search(title)
                                       and not _ALL_LANG_RE.search(title))):
        if not _ASSET_MARK.search(title):
            return "required"
    for sentence in sentences(text or ""):
        mentions = [m for m in rx.finditer(sentence)]
        if is_french and not mentions and _BILINGUAL.search(sentence):
            others = [m for m in _ALL_LANG_RE.finditer(sentence)
                      if not re.fullmatch(r"fran[cç]ais|francais|french", m.group(0), re.I)]
            if not others:
                mentions = list(_BILINGUAL.finditer(sentence))
        for m in mentions:
            marks = [(x.start(), x.end(), "required") for x in _REQ_MARK.finditer(sentence)]
            marks += [(x.start(), x.end(), "asset") for x in _ASSET_MARK.finditer(sentence)]
            # An asset marker wins over a requirement word it overlaps ("not required").
            asset_spans = [(s, e) for s, e, k in marks if k == "asset"]
            marks = [(s, e, k) for s, e, k in marks
                     if k == "asset" or not any(a <= s and e <= b for a, b in asset_spans)]
            after = [(s - m.end(), k) for s, e, k in marks if s >= m.end() and s - m.end() <= _MARK_DISTANCE]
            before = [(m.start() - e, k) for s, e, k in marks if e <= m.start() and m.start() - e <= _MARK_DISTANCE]
            kind = ""
            if after:
                kind = min(after)[1]
            elif before:
                kind = min(before)[1]
            elif _BILINGUAL.fullmatch(m.group(0)):
                kind = "required"
            if kind == "required":
                return "required"
            if kind == "asset":
                strongest = "asset"
    return strongest


# --------------------------------------------------------------------------- eligibility

_US = r"(?:u\.?\s?s\.?(?:a\.?)?|united\s+states)"
_US_ONLY_TEXT = re.compile(
    rf"\b(?:must|need\s+to|required\s+to|have\s+to|shall)\s+(?:be|hold|have)\s+(?:an?\s+|current\s+)?"
    rf"{_US}\s+(?:citizen(?:ship)?|person|national)|"
    rf"\brequires?\s+(?:you\s+to\s+be\s+)?(?:an?\s+)?{_US}\s+(?:citizen(?:ship)?|person|national)|"
    rf"\b{_US}\s+(?:citizens?|persons?|nationals?)\s+(?:only|required)|"
    rf"\b(?:citizenship|u\.?s\.?\s+citizen)\s+(?:of|in)\s+the\s+{_US}\s+is\s+required|"
    rf"\b(?:an?\s+)?(?:active|current|valid)\s+{_US}\s+(?:government\s+|federal\s+|dod\s+)?"
    rf"(?:security\s+)?clearance|"
    rf"\b(?:ability\s+to\s+(?:obtain|hold)|eligible\s+(?:for|to\s+obtain))\s+(?:an?\s+)?{_US}\s+"
    rf"(?:government\s+|federal\s+|dod\s+)?(?:security\s+)?clearance|"
    rf"\bts\s*/\s*sci\b|\btop\s+secret\s*/\s*sci\b",
    re.IGNORECASE)


def us_only_phrase(text: str) -> str:
    """A US-citizen, US-person or US-clearance requirement, or ''. A Canadian phrase
    ('reliability status', 'Government of Canada security clearance') and export-control
    boilerplate are not matched."""
    m = _US_ONLY_TEXT.search(text or "")
    return m.group(0).strip() if m else ""


_NO_SPONSOR = re.compile(
    r"\b(?:no\s+(?:visa\s+)?sponsorship|(?:will|do|does|can|could)\s*(?:not|n't)\s+(?:be\s+able\s+to\s+)?"
    r"(?:provide\s+|offer\s+)?(?:visa\s+|work\s+permit\s+)?sponsor\w*|"
    r"(?:unable|not\s+able|cannot|can't)\s+to?\s*(?:provide\s+|offer\s+)?(?:visa\s+)?sponsor\w*|"
    r"without\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+)?(?:visa\s+)?sponsorship|"
    r"sponsorship\s+is\s+not\s+(?:available|offered|provided))\b", re.I)


def no_sponsorship_phrase(text: str) -> str:
    m = _NO_SPONSOR.search(text or "")
    return m.group(0).strip() if m else ""


_GENERIC_SCHOOL_WORDS = {"university", "college", "institute", "of", "the", "school", "and", "at",
                         "polytechnique", "technology", "de", "du", "ecole", "universite", "state"}
_SCHOOL_NAMED = re.compile(
    r"(?:enrolled|enrolment|enrollment|students?|program|programme|candidates?)"
    r"[^.]{0,60}\b(?:at|from|with)\b[^.]{0,80}?"
    r"\b((?:University|College|Institute|Polytechnique|École|Ecole)\s+(?:of\s+|de\s+)?"
    r"[A-Z][\w'&.\-]+(?:\s+[A-Z][\w'&.\-]+){0,3}|"
    r"[A-Z][\w'&.\-]+(?:\s+[A-Z][\w'&.\-]+){0,2}\s+(?:University|College|Institute)|"
    r"SFU|UBC|BCIT|ETS|U\s?of\s?T|UofT|UCLA|UCSD|UIUC|MIT|NYU|CMU)")
_SCHOOL_VETO = re.compile(
    r"(alumni|our team includes|graduates of|hired from|founded (at|by)|partners? with|"
    r"such as|for example|including but not limited)", re.I)


def _school_tokens(name: str) -> set[str]:
    words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if w]
    sig = {w for w in words if w not in _GENERIC_SCHOOL_WORDS and len(w) > 1}
    acro = "".join(w[0] for w in words if w not in ("of", "the", "and", "at", "de", "du"))
    if len(acro) >= 3:
        sig.add(acro)
    return sig


def school_restriction(text: str, user_schools: list[str]) -> str:
    """The school a posting says it recruits from when none is the user's, else ''. A note
    only: the form often accepts other schools, so it never removes a posting."""
    if not user_schools:
        return ""
    mine = set().union(*(_school_tokens(s) for s in user_schools if s))
    if not mine:
        return ""
    named: list[str] = []
    for m in _SCHOOL_NAMED.finditer(text or ""):
        window = (text or "")[max(0, m.start() - 80):m.end() + 40]
        if _SCHOOL_VETO.search(window):
            continue
        named.append(m.group(1).strip())
    if not named:
        return ""
    for n in named:
        if _school_tokens(n) & mine or fold(n).replace(" ", "") in mine:
            return ""
    return named[0].rstrip(" .,;:")
