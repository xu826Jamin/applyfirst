"""The ideal resume for a role group: what a strong early-career resume in that field puts first.

Written once per group by Claude and cached (it describes the field, not the person, so it never
goes stale with the person's experience). It only steers which of the person's own confirmed lines
are picked and in what order; it never adds a line or a word to the resume.
"""
from __future__ import annotations

import json

from .. import claude, config, store
from . import tailor

FIELD_LABELS = {
    "software": "software engineering", "hardware": "hardware engineering", "data-ml": "data science and machine learning",
    "quant": "quantitative finance and trading technology", "product": "product management", "design": "product and UX design",
    "it-security": "IT and cybersecurity", "research": "research", "mechanical": "mechanical engineering",
    "electrical": "electrical engineering", "civil": "civil engineering", "business": "business",
    "finance": "finance", "marketing": "marketing", "sales": "sales", "operations": "operations",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {"type": "array", "items": {"type": "string"}, "maxItems": 40},
        "summary": {"type": "string"},
    },
    "required": ["terms"],
}

PROMPT = (
    "You are a recruiter who screens early-career and internship resumes for {label} roles.\n"
    "List the skills, tools, languages and kinds of work that the strongest resumes in this field\n"
    "show first, most important first. Plain terms a resume would actually contain (for example\n"
    "'Python', 'PCB design', 'A/B testing'), at most 40. Then one sentence on what the best\n"
    "resumes in this field lead with. JSON only."
)


def groups(settings: dict) -> list[str]:
    """The role groups to keep an ideal resume for: the user's pick, else their search fields."""
    picked = [g for g in (config.get(settings, "apply.resume_groups", []) or []) if g]
    return picked or [f for f in (config.get(settings, "search.fields", []) or []) if f] or ["software"]


def _path(group: str):
    d = config.path("resumes") / "ideal"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{group}.json"


def outline(group: str, run_id: str | None = None) -> dict:
    """The cached ideal for one group, asking Claude the first time. {} when Claude is not
    available; callers then fall back to choosing by role type alone."""
    p = _path(group)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if not claude.available():
        return {}
    res = claude.run(PROMPT.format(label=FIELD_LABELS.get(group, group)), run_id,
                     json_schema=SCHEMA, max_turns=2, timeout=300)
    data = res.structured if res.ok and isinstance(res.structured, dict) else None
    if not data or not data.get("terms"):
        if run_id:
            store.log(run_id, f"ideal resume for {group}: Claude gave no outline ({res.error or 'empty'}); choosing by role type")
        return {}
    data = {"group": group, "terms": [str(t).strip() for t in data["terms"] if str(t).strip()][:40],
            "summary": str(data.get("summary", "")).strip(), "built_at": store.now()}
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def wanted(group: str, entries: list[dict], run_id: str | None = None) -> set[str]:
    """The ideal's terms, mapped onto the person's own skill vocabulary (only terms they have)."""
    terms = outline(group, run_id).get("terms") or []
    if not terms:
        return set()
    return tailor.wanted_terms({"title": "", "description": "\n".join(terms)}, entries)
