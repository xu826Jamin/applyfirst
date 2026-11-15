"""Order postings: newest, deadline, company, or a rough match with the user's experience.

Ordering rules ported from the private pipeline's queue order: a deadline still ahead sorts
soonest first, no deadline and a deadline already past sort after, and a past date is never
"soonest". Ties fall to company, title and id so the same data always gives the same order.

The match is deliberately rough: how many skills and tools the posting asks for also appear in
the user's confirmed experience (tags and text). It is a sort key, labelled as rough.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from functools import lru_cache

from .text import fold, now_utc, parse_date, parse_dt

ORDER_KEYS = ("newest", "deadline", "company", "match")

# A curated vocabulary: real skills, tools and methods. Function words cannot appear here, so
# they can never count as a match. Each entry is the canonical name; variants are regexes.
_VOCAB = {
    "python": r"python", "java": r"java(?!\s*script)", "javascript": r"javascript|\bjs\b",
    "typescript": r"typescript", "c++": r"c\+\+", "c#": r"c#", "rust": r"rust",
    "go": r"golang|\bgo\s+(?:programming|developer|language)", "kotlin": r"kotlin",
    "swift": r"swift(?:ui)?", "sql": r"\bsql\b|postgres(?:ql)?|mysql|sqlite", "nosql": r"nosql|mongodb|dynamodb|redis",
    "r": r"\bR\b(?=\s+(?:programming|language|studio|and|or|,))", "matlab": r"matlab",
    "bash": r"\bbash\b|shell\s+script", "verilog": r"verilog|systemverilog", "vhdl": r"vhdl",
    "fpga": r"fpga", "asic": r"asic", "embedded": r"embedded", "rtos": r"rtos|freertos|zephyr",
    "linux": r"linux", "git": r"\bgit(?:hub|lab)?\b", "docker": r"docker", "kubernetes": r"kubernetes|\bk8s\b",
    "aws": r"\baws\b|amazon web services", "azure": r"azure", "gcp": r"\bgcp\b|google cloud",
    "terraform": r"terraform", "ci/cd": r"ci\s*/\s*cd|continuous integration|jenkins|github actions",
    "react": r"react(?:\.js|js)?\b", "angular": r"angular", "vue": r"vue(?:\.js)?\b",
    "node": r"node(?:\.js|js)\b", "django": r"django", "flask": r"flask", "fastapi": r"fastapi",
    "spring": r"spring\s+boot|spring\b", ".net": r"\.net\b|asp\.net", "rest apis": r"rest(?:ful)?\s+apis?|\bapis?\b",
    "graphql": r"graphql", "html/css": r"\bhtml\b|\bcss\b", "machine learning": r"machine\s+learning|\bml\b",
    "deep learning": r"deep\s+learning|neural\s+networks?", "pytorch": r"pytorch", "tensorflow": r"tensorflow",
    "nlp": r"\bnlp\b|natural\s+language", "computer vision": r"computer\s+vision|opencv",
    "data analysis": r"data\s+analy(?:sis|tics)", "pandas": r"pandas", "numpy": r"numpy",
    "spark": r"\bspark\b|pyspark", "tableau": r"tableau", "power bi": r"power\s*bi", "excel": r"\bexcel\b",
    "statistics": r"statistic(?:s|al)", "probability": r"probability|stochastic", "optimization": r"optimi[sz]ation",
    "algorithms": r"algorithms?|data\s+structures", "distributed systems": r"distributed\s+systems",
    "microservices": r"microservices?", "testing": r"unit\s+test|test\s+automation|pytest|junit|\bqa\b",
    "agile": r"agile|scrum", "security": r"cyber\s*security|infosec|penetration\s+test",
    "networking": r"tcp/ip|networking|\bdns\b", "robotics": r"robotics|\bros\b", "cad": r"solidworks|autocad|\bcad\b",
    "circuit design": r"circuit\s+design|pcb|altium|analog|\brf\b", "control systems": r"control\s+systems?|\bpid\b",
    "finance": r"financial\s+modell?ing|derivatives|equities|fixed\s+income|portfolio",
    "trading": r"trading|low[\s-]latency|market\s+making", "accounting": r"accounting|bookkeeping",
    "research": r"research", "writing": r"technical\s+writing|copywriting", "figma": r"figma",
    "ux": r"\bux\b|user\s+research|user\s+experience", "seo": r"\bseo\b|google\s+analytics",
    "social media": r"social\s+media", "crm": r"salesforce|\bcrm\b|hubspot", "project management": r"project\s+management",
    "customer service": r"customer\s+service|customer\s+support",
}


@lru_cache(maxsize=1)
def _compiled() -> dict:
    out = {}
    for k, v in _VOCAB.items():
        if k == "r":
            out[k] = re.compile(v)
        else:
            out[k] = re.compile(r"(?<![A-Za-z0-9])(?:" + v + r")(?![A-Za-z0-9])", re.I)
    return out


def vocab_in(text: str) -> set:
    text = text or ""
    return {k for k, rx in _compiled().items() if rx.search(text)}


def experience_profile(rows: list[dict] | None) -> tuple[set, set]:
    """(vocabulary terms, tag phrases) from the user's confirmed experience rows."""
    terms: set = set()
    tags: set = set()
    for r in rows or []:
        if not r.get("confirmed"):
            continue
        blob = " ".join(str(r.get(k) or "") for k in ("title", "org", "text"))
        try:
            t = json.loads(r.get("tags") or "[]") if isinstance(r.get("tags"), str) else (r.get("tags") or [])
        except ValueError:
            t = []
        for tag in t:
            tag = fold(tag).strip()
            if len(tag) > 1:
                tags.add(tag)
        terms |= vocab_in(blob + " " + " ".join(map(str, t)))
    return terms, tags


def rough_match(posting: dict, profile_terms: set, tags: set) -> dict:
    """{shared, asked, terms}: the skills the posting names that the user's experience also names."""
    text = f"{posting.get('title') or ''}\n{posting.get('description') or ''}"
    asked = vocab_in(text)
    low = fold(text)
    for tag in tags:
        if re.search(r"(?<![a-z0-9])" + re.escape(tag) + r"(?![a-z0-9])", low):
            asked.add(tag)
    shared = {t for t in asked if t in profile_terms or t in tags}
    return {"shared": len(shared), "asked": len(asked), "terms": sorted(shared)[:8]}


def _match_score(m: dict) -> float:
    if not m["asked"]:
        return 0.0
    return m["shared"] + m["shared"] / (m["asked"] + 4)


def _first_dt(p: dict):
    return parse_dt(p.get("posted_at")) or parse_dt(p.get("first_seen_at"))


def _deadline(p: dict) -> dt.date | None:
    return parse_date(p.get("deadline"))


def _key(name: str, p: dict, today: dt.date, match_by_id: dict):
    """A sortable tuple for one ordering key. Smaller sorts first."""
    if name == "newest":
        d = _first_dt(p)
        return (0, -d.timestamp()) if d else (1, 0.0)
    if name == "deadline":
        d = _deadline(p)
        if d is not None and d >= today:
            return (0, d.toordinal())
        return (1, 0)               # none, or already past: after every upcoming deadline
    if name == "company":
        return (0, fold(p.get("company")).strip())
    if name == "match":
        return (0, -_match_score(match_by_id[id(p)]))
    return (0, 0)


def order(postings: list[dict], settings: dict, today: dt.date | None = None,
          experience: list[dict] | None = None) -> list[dict]:
    """Postings sorted by queue.order_by, then queue.then_by (newest | deadline | company | match).
    Ties fall to company, title and id so the result is repeatable. Returns a new list."""
    q = (settings or {}).get("queue") or {}
    first = q.get("order_by") if q.get("order_by") in ORDER_KEYS else "newest"
    second = q.get("then_by") if q.get("then_by") in ORDER_KEYS else "deadline"
    today = today or now_utc().date()
    items = list(postings or [])
    match_by_id: dict = {}
    if "match" in (first, second):
        terms, tags = experience_profile(experience)
        for p in items:
            match_by_id[id(p)] = rough_match(p, terms, tags)

    def sort_key(p: dict):
        return (_key(first, p, today, match_by_id), _key(second, p, today, match_by_id),
                fold(p.get("company")).strip(), fold(p.get("title")).strip(), str(p.get("id") or ""))

    return sorted(items, key=sort_key)
