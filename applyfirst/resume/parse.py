"""PDF resume -> experience bank rows.

import_pdf reads the text with pypdf and has Claude split it into entries and bullets with tags.
When Claude is not installed, or fails, or returns something unusable, a plain parser (section
headings, bullet glyphs, date ranges) does the same job. Either way every row lands unconfirmed:
nothing reaches a resume until the user has looked at it.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import claude, config, store
from . import bank, tailor

ROLE_TYPES = ["software", "hardware", "data-ml", "quant", "product", "design", "it-security",
              "research", "mechanical", "electrical", "civil", "business", "finance", "marketing",
              "sales", "operations", "other"]
MAX_PROMPT_CHARS = 24000

# --------------------------------------------------------------------------- text


def extract_text(path: str) -> str:
    import pypdf
    try:
        reader = pypdf.PdfReader(path)
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Could not read that PDF ({e.__class__.__name__}). Is it a resume PDF?") from e
    text = text.replace("\r", "")
    if len(text.strip()) < 40:
        raise ValueError("That PDF has no readable text (it may be a scan). Export your resume as a "
                         "text PDF from Word, Google Docs or similar, then try again.")
    return text


# --------------------------------------------------------------------------- heuristic parser

SECTION_WORDS = {
    "experience": {"experience", "work experience", "professional experience", "employment",
                   "employment history", "work history", "relevant experience", "internships",
                   "industry experience", "career history"},
    "projects": {"projects", "personal projects", "selected projects", "academic projects",
                 "side projects", "technical projects", "project experience"},
    "education": {"education", "academic background", "education and training", "academics"},
    "skills": {"skills", "technical skills", "core skills", "key skills", "technologies",
               "skills and tools", "tools and technologies", "technical proficiencies", "skills and interests"},
    "other": {"leadership", "activities", "leadership and activities", "awards", "honors", "honours",
              "awards and honors", "awards and honours", "volunteer", "volunteering", "volunteer experience",
              "extracurricular", "extracurriculars", "extracurricular activities", "certifications",
              "publications", "interests", "achievements", "involvement", "community", "leadership experience",
              "certifications and awards", "additional", "activities and other", "other activities",
              "activities and interests", "other", "additional information", "leadership and involvement",
              "extracurricular and leadership", "honors and awards", "awards and certifications"},
}
IGNORED_HEADINGS = {"summary", "profile", "objective", "professional summary", "about me", "career objective"}

GLYPH_RE = re.compile(r"^\s*[•●▪◦‣⁃∙·■–—\-\*>→]\s+")
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|Spring|Summer|Fall|Autumn|Winter)\.?")
_DATE = rf"(?:(?:{_MONTH})\s+)?(?:19|20)\d{{2}}|\d{{1,2}}/(?:19|20)\d{{2}}"
_END = rf"(?:{_DATE}|Present|Current|Now|Ongoing)"
RANGE_RE = re.compile(rf"(?:(?:Expected|Anticipated)\s+)?(?:{_DATE})\s*(?:-|–|—|to)\s*{_END}", re.I)
SINGLE_RE = re.compile(rf"(?:(?:Expected|Anticipated)\s+)?(?:{_DATE})", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}|\b\d{3}[\s.-]\d{4}\b")
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com)/[\w./%-]+", re.I)
TITLE_WORDS = re.compile(r"\b(intern|engineer|developer|manager|analyst|assistant|lead|co-?op|researcher|"
                         r"director|designer|associate|coordinator|consultant|president|captain|technician|"
                         r"specialist|student|member|volunteer|tutor|teaching|founder|officer|chair|"
                         r"representative|programmer|architect|scientist|administrator)\b", re.I)
SCHOOL_WORDS = re.compile(r"\b(university|college|institute|school|academy|polytechnic|universit\w+)\b", re.I)
DEGREE_WORDS = re.compile(r"\b(b\.?eng|b\.?sc|b\.?a\.?|bachelor|master|m\.?sc|m\.?eng|mba|ph\.?d|diploma|"
                          r"degree|associate|certificate|b\.?s\.?|m\.?s\.?)\b", re.I)
PLACE_RE = re.compile(r"^[A-Z][A-Za-z.']*(?:[ -][A-Za-z.']+){0,3},\s*[A-Z]{2}(?:,\s*[A-Za-z ]+)?$")

COMMON_TECH = """python java javascript typescript c c++ c# go rust ruby php swift kotlin sql r matlab bash
html css react angular vue node.js express django flask fastapi spring rails next.js tailwind docker
kubernetes aws gcp azure linux git github jenkins terraform postgresql mysql mongodb redis sqlite
pandas numpy pytorch tensorflow scikit-learn spark kafka graphql rest tableau excel figma verilog
vhdl fpga arduino raspberry-pi stm32 cad solidworks autocad""".split()

ROLE_KEYWORDS = {
    "software": ["software", "web app", "website", "api", "backend", "front-end", "frontend", "full-stack",
                 "full stack", "application", "mobile app", "react", "django", "javascript", "typescript"],
    "data-ml": ["machine learning", "neural", "dataset", "data pipeline", "analytics", "pandas",
                "tensorflow", "pytorch", "classification", "etl", "dashboard"],
    "hardware": ["fpga", "verilog", "vhdl", "circuit", "pcb", "embedded", "firmware", "microcontroller",
                 "oscilloscope", "soldering"],
    "quant": ["trading", "quantitative", "portfolio", "backtest", "options pricing", "algorithmic"],
    "research": ["research", "published", "paper", "experiment", "thesis", "laboratory"],
    "product": ["product", "roadmap", "stakeholder", "user research", "requirements"],
    "design": ["ui/ux", "design system", "wireframe", "prototype", "figma"],
    "mechanical": ["cad", "solidworks", "mechanical", "machining", "thermal", "3d print"],
    "business": ["sales", "customer", "revenue", "client", "marketing", "operations"],
}


def _heading(line: str) -> str | None:
    s = re.sub(r"[:\s]+$", "", line.strip()).lower().replace("&", "and")
    s = re.sub(r"\s+", " ", s)
    if len(s) > 45:
        return None
    if s in IGNORED_HEADINGS:
        return "ignore"
    for sec, words in SECTION_WORDS.items():
        if s in words:
            return sec
    return None


_SMALL = {"and", "of", "the", "for", "in", "at", "a", "an", "to", "on", "with", "&", "-", "|"}


def _heading_like(s: str) -> bool:
    """A short line of mostly Title Case words with no closing full stop: an entry heading, not a sentence."""
    s = s.strip()
    if len(s) > 80 or s.endswith(".") or s.endswith(";"):
        return False
    words = [w for w in re.split(r"[\s,]+", s) if w and w.lower() not in _SMALL]
    if not words:
        return False
    caps = sum(1 for w in words if w[:1].isupper() or not w[:1].isalpha())
    return caps / len(words) >= 0.6


def _split_top(s: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        depth += (ch == "(") - (ch == ")")
        if ch in ",;|•" and depth <= 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" \t,|-–—·")


def _contact(header_lines: list[str]) -> dict:
    text = "\n".join(header_lines)
    out = {"name": "", "email": "", "phone": "", "location": "", "linkedin": "", "github": "", "portfolio": ""}
    for ln in header_lines:
        ln = ln.strip()
        if ln and not EMAIL_RE.search(ln) and not re.search(r"\d", ln) and "http" not in ln.lower() \
                and len(ln.split()) <= 5:
            out["name"] = ln.title() if ln.isupper() else ln
            break
    m = EMAIL_RE.search(text)
    out["email"] = m.group(0) if m else ""
    m = PHONE_RE.search(text)
    out["phone"] = m.group(0).strip() if m else ""
    for u in URL_RE.findall(text):
        key = "linkedin" if "linkedin" in u.lower() else "github"
        out[key] = out[key] or (u if u.lower().startswith("http") else "https://" + u)
    for piece in re.split(r"[|•·\n]", text):
        piece = piece.strip()
        if PLACE_RE.match(piece):
            out["location"] = piece
            break
    return out


def _assign(parts: list[str], section: str) -> tuple[str, str]:
    """(title, org) from the heading pieces of an entry."""
    flat = []
    for p in (_clean(x) for x in parts):
        sub = [x for x in re.split(r"\s+[|–—]\s+|\s+-\s+|\s*\|\s*| at | @ ", p) if x.strip()]
        flat += sub if len(sub) > 1 else [p]
    parts = [_clean(p) for p in flat if _clean(p) and not PLACE_RE.match(_clean(p))]
    if not parts:
        return "", ""
    if section == "education":
        school = next((p for p in parts if SCHOOL_WORDS.search(p)), "")
        degree = next((p for p in parts if DEGREE_WORDS.search(p) and p != school), "")
        rest = [p for p in parts if p not in (school, degree)]
        return degree or (rest[0] if rest and not school else ""), school or (rest[0] if rest else "")
    if len(parts) == 1:
        # "Title, Org" written on one line
        comma = [x.strip() for x in parts[0].split(", ")]
        if len(comma) == 2 and section in ("experience", "other") and not PLACE_RE.match(parts[0]):
            parts = comma
        else:
            return parts[0], ""
    title = next((p for p in parts if TITLE_WORDS.search(p)), parts[0])
    org = ", ".join(p for p in parts if p != title)
    return title, org


def _tags_for(text: str, vocab: set[str]) -> list[str]:
    tags = [v for v in sorted(vocab) if tailor.mentions(v, text)]
    low = text.lower()
    for role, words in ROLE_KEYWORDS.items():
        if any(w in low for w in words):
            tags.append(f"{bank.ROLE_PREFIX}{role}")
    return tags


def heuristic_parse(text: str) -> dict:
    """{contact, entries} from resume text, without Claude. Entries are
    {section, title, org, dates, tags, bullets: [{text, tags}]}."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    header, body, section = [], [], None
    for ln in lines:
        h = _heading(ln)
        if h:
            section = h
            body.append(("#", h))
            continue
        if section is None:
            header.append(ln)
        else:
            body.append((section_marker(body), ln))
    contact = _contact(header)
    glyph_mode = sum(1 for ln in lines if GLYPH_RE.match(ln)) >= 2
    if not any(m == "#" for m, _ in body) and header:
        # no headings at all: everything after the contact lines is experience
        body = [("#", "experience")] + [("experience", ln) for ln in header[2:]]
    entries: list[dict] = []
    skill_vocab: set[str] = set()

    maxlen = max((len(ln.strip()) for ln in lines), default=1)
    last_len = 0
    cur_section, cur, pending, last_label = None, None, [], "Skills"
    for marker, ln in body:
        if marker == "#":
            cur_section, cur, pending = ln, None, []
            continue
        if cur_section == "ignore":
            continue
        s = ln.strip()
        if cur_section == "skills":
            g = GLYPH_RE.sub("", s)
            if ":" in g and len(g.split(":")[0]) < 40:
                label, rest = g.split(":", 1)
                last_label = _clean(label) or "Skills"
            else:
                rest = g
            for term in _split_top(rest):
                term = _clean(term)
                if term and len(term) < 50:
                    entries.append({"section": "skills", "title": term, "org": last_label, "dates": "",
                                    "tags": [], "bullets": []})
                    skill_vocab.add(term.lower())
            continue
        is_bullet = bool(GLYPH_RE.match(s))
        if is_bullet:
            btxt = _clean(GLYPH_RE.sub("", s))
            if pending or cur is None:
                title, org = _assign(pending, cur_section or "experience") if pending else ("", "")
                cur = {"section": cur_section or "experience", "title": title, "org": org, "dates": "",
                       "tags": [], "bullets": []}
                entries.append(cur)
                pending = []
            cur["bullets"].append({"text": btxt, "tags": []})
            last_len = len(s)
            continue
        dm = RANGE_RE.search(s) or SINGLE_RE.search(s)
        if dm and len(s) - len(dm.group(0)) < 110 and not (s.endswith(".") and len(s) > 80):
            before, after = s[:dm.start()], s[dm.end():]
            parts = pending + [p for p in (before, after) if _clean(p)]
            title, org = _assign(parts, cur_section or "experience")
            cur = {"section": cur_section or "experience", "title": title, "org": org,
                   "dates": _clean(dm.group(0)), "tags": [], "bullets": []}
            entries.append(cur)
            pending = []
            continue
        if cur and cur["bullets"]:
            prev = cur["bullets"][-1]["text"]
            # A wrapped bullet: the line before ran to the right edge (about the longest line on
            # the page) and did not end a sentence, or this line starts in lower case.
            # Without bullet marks, every line is a bullet start unless it begins in lower case.
            full = glyph_mode and last_len >= 0.82 * maxlen and not re.search(r"[.!?;:]$", prev)
            if full or s[:1].islower():
                cur["bullets"][-1]["text"] = _clean(prev + " " + s)
                last_len = len(s)
                continue
        if cur_section == "education" and cur is not None and not pending:
            if not cur["title"] and DEGREE_WORDS.search(s):
                cur["title"] = _clean(s)
                continue
            if not cur["org"] and SCHOOL_WORDS.search(s):
                cur["org"] = _clean(s)
                continue
            cur["bullets"].append({"text": _clean(s), "tags": []})
            continue
        if not glyph_mode:
            # The text layer carries no bullet marks (many PDFs draw them as shapes), so a short
            # Title Case line is an entry heading and any other line is a bullet.
            if _heading_like(s):
                if cur and not cur["bullets"] and not cur["org"] and not pending and cur["title"]:
                    cur["org"] = _clean(s)
                else:
                    pending.append(s)
                continue
            if pending or cur is None:
                title, org = _assign(pending, cur_section or "experience") if pending else ("", "")
                cur = {"section": cur_section or "experience", "title": title, "org": org, "dates": "",
                       "tags": [], "bullets": []}
                entries.append(cur)
                pending = []
            cur["bullets"].append({"text": _clean(s), "tags": []})
            last_len = len(s)
            continue
        pending.append(s)
    if pending:
        title, org = _assign(pending, cur_section or "experience")
        entries.append({"section": cur_section or "experience", "title": title, "org": org, "dates": "",
                        "tags": [], "bullets": []})
    entries = [e for e in entries if e["section"] != "ignore" and (e["title"] or e["org"] or e["bullets"])]
    vocab = skill_vocab | set(COMMON_TECH)
    for e in entries:
        if e["section"] == "skills":
            continue
        roles = set()
        for b in e["bullets"]:
            b["tags"] = _tags_for(b["text"], vocab)
            roles |= {t for t in b["tags"] if t.startswith(bank.ROLE_PREFIX)}
        e["tags"] = sorted(roles)
    return {"contact": contact, "entries": entries}


def section_marker(body: list) -> str:
    for m, v in reversed(body):
        if m == "#":
            return v
    return "experience"


# --------------------------------------------------------------------------- Claude

SCHEMA = {
    "type": "object",
    "properties": {
        "contact": {"type": "object", "properties": {
            k: {"type": "string"} for k in ("name", "email", "phone", "location", "linkedin", "github",
                                            "portfolio")}},
        "entries": {"type": "array", "items": {"type": "object", "properties": {
            "section": {"type": "string", "enum": ["experience", "projects", "education", "other"]},
            "title": {"type": "string"}, "org": {"type": "string"}, "dates": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "string"}},
                "tools": {"type": "array", "items": {"type": "string"}},
                "role_types": {"type": "array", "items": {"type": "string", "enum": ROLE_TYPES}},
            }, "required": ["text"]}},
        }, "required": ["section", "title", "bullets"]}},
        "skills": {"type": "array", "items": {"type": "object", "properties": {
            "group": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}},
            "required": ["group", "items"]}},
    },
    "required": ["entries"],
}

PROMPT = """You are turning a person's resume text into structured rows for their experience bank.

Rules:
- Copy every bullet's text EXACTLY as written in the resume. Do not reword, shorten, merge, or add anything.
  Join a bullet that was wrapped across lines into one line, nothing more.
- Entries: one per job, project, school, or activity. title = the role, project name, or degree;
  org = the employer, school, or tech line; dates exactly as written ("" if none).
- section is one of experience, projects, education, other (awards, leadership, volunteering, certifications).
  Skills lists go in "skills" as {{group, items}}, one item per term.
- For each bullet give skills and tools it uses (lower-case, only terms the bullet or the entry actually
  names) and role_types it would help with, from: {roles}.
- Put the person's name, email, phone, location and profile links in "contact".
- Invent nothing. If something is not in the text, leave it out.

RESUME TEXT:
{text}
"""


def _from_claude(data: dict) -> dict | None:
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    entries = []
    for e in data["entries"]:
        if not isinstance(e, dict) or e.get("section") not in ("experience", "projects", "education", "other"):
            continue
        bullets = []
        for b in e.get("bullets") or []:
            if not isinstance(b, dict) or not str(b.get("text", "")).strip():
                continue
            tags = [str(t).lower().strip() for t in (b.get("skills") or []) + (b.get("tools") or []) if str(t).strip()]
            tags += [f"{bank.ROLE_PREFIX}{r}" for r in (b.get("role_types") or []) if r in ROLE_TYPES]
            bullets.append({"text": re.sub(r"\s+", " ", str(b["text"])).strip(), "tags": sorted(set(tags))})
        roles = sorted({t for b in bullets for t in b["tags"] if t.startswith(bank.ROLE_PREFIX)})
        entries.append({"section": e["section"], "title": str(e.get("title", "")).strip(),
                        "org": str(e.get("org", "")).strip(), "dates": str(e.get("dates", "")).strip(),
                        "tags": roles, "bullets": bullets})
    for g in data.get("skills") or []:
        if not isinstance(g, dict):
            continue
        label = str(g.get("group") or "Skills").strip()
        for term in g.get("items") or []:
            if str(term).strip():
                entries.append({"section": "skills", "title": str(term).strip(), "org": label, "dates": "",
                                "tags": [], "bullets": []})
    if not entries:
        return None
    contact = {k: str(v) for k, v in (data.get("contact") or {}).items() if isinstance(v, str)}
    return {"contact": contact, "entries": entries}


def claude_parse(text: str, run_id: str | None) -> dict | None:
    try:
        res = claude.run(PROMPT.format(roles=", ".join(ROLE_TYPES), text=text[:MAX_PROMPT_CHARS]),
                         run_id, json_schema=SCHEMA, max_turns=3, timeout=600)
    except Exception as e:  # noqa: BLE001  any failure falls back to the plain parser, and is logged
        if run_id:
            store.log(run_id, f"resume import: Claude call failed ({e}); using the plain parser")
        return None
    if not res.ok or res.structured is None:
        if run_id:
            store.log(run_id, f"resume import: Claude gave no usable answer ({res.error[:200]}); using the plain parser")
        return None
    parsed = _from_claude(res.structured)
    if parsed is None and run_id:
        store.log(run_id, "resume import: Claude's answer had no entries; using the plain parser")
    return parsed


# --------------------------------------------------------------------------- entry point


def _fill_profile(contact: dict) -> None:
    """Fill blank profile fields from the resume's header. Never overwrites what the user entered."""
    prof = config.load_profile()
    changed = False
    name = (contact.get("name") or "").strip()
    if name and not prof["name"]["first"]:
        bits = name.split()
        prof["name"]["first"] = bits[0]
        prof["name"]["last"] = " ".join(bits[1:])
        changed = True
    for key in ("email", "phone"):
        if contact.get(key) and not prof.get(key):
            prof[key] = contact[key]
            changed = True
    for key in ("linkedin", "github", "portfolio"):
        if contact.get(key) and not prof["links"].get(key):
            prof["links"][key] = contact[key]
            changed = True
    loc = contact.get("location", "")
    if loc and not prof["location"]["city"]:
        bits = [x.strip() for x in loc.split(",")]
        prof["location"]["city"] = bits[0]
        if len(bits) > 1:
            prof["location"]["region"] = bits[1]
        changed = True
    if changed:
        config.save_profile(prof)


def import_pdf(path: str, run_id: str | None = None) -> list[dict]:
    """Read a resume PDF and store its content as unconfirmed experience rows.

    Returns the stored rows (entries and bullets). Unconfirmed rows from an earlier import are
    replaced; confirmed rows are kept and not duplicated. Blank profile fields (name, email,
    phone, links) are filled from the resume header."""
    text = extract_text(str(Path(path)))
    parsed = claude_parse(text, run_id)
    source = "Claude"
    if parsed is None:
        parsed = heuristic_parse(text)
        source = "plain parser"
    norm_pdf = bank.norm_text(text)
    for e in parsed["entries"]:
        for b in e["bullets"]:
            if bank.norm_text(b["text"]) not in norm_pdf and bank.norm_text(b["text"])[:60] not in norm_pdf:
                if "needs-review" not in b["tags"]:
                    b["tags"] = b["tags"] + ["needs-review"]
    rows = bank.replace_unconfirmed(parsed["entries"])
    _fill_profile(parsed.get("contact") or {})
    if run_id:
        n_b = sum(1 for r in rows if r["parent_id"])
        store.log(run_id, f"resume import ({source}): {len(rows) - n_b} entries, {n_b} bullets")
    return rows
