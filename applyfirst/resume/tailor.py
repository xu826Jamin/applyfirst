"""Choosing which true lines go on a page, and in what order. Pure functions, no I/O.

THE INVARIANT: every line on a generated resume is copied verbatim from a confirmed bank row.
Tailoring means which bank lines appear and in what order; a posting can promote a bullet, it
can never cause a claim to exist.

Rules carried over from the pipeline this was ported from:

- Relevance reorders inside a section and never across one. An entry's section is a property
  of the work, not of the posting.
- A one-page overflow sheds bullets before whole entries, never an Experience entry, never a
  pinned entry, never an "always" bullet.
- Technical Skills is a short list, not the inventory: a term prints only when a bullet on the
  page uses it (its text or its tags), and the terms the posting asks for rank first.
- Two bullets of one entry making the same distinctive claim (a number, a named tool) count as
  a duplicate; the picker skips the second one unless nothing else fills the room.
"""
from __future__ import annotations

import re

from . import bank

# Sections printed from entries, in the order the renderer uses them.
BODY_SECTIONS = ["experience", "projects", "education", "other"]
SECTION_ORDER = BODY_SECTIONS          # relative order for sorting; rendering may move education

# Most bullets one entry shows before the page-fitter starts trimming.
MAX_BULLETS = {"experience": 4, "projects": 3, "education": 2, "other": 3}
SKILL_CAP_LANGUAGES = 4
SKILL_CAP_OTHER = 6


# --------------------------------------------------------------------------- matching


def mentions(alias: str, text: str) -> bool:
    """Whole-term match. A 1 or 2 letter term ('C', 'R', 'Go') is case-sensitive and never
    matches inside 'C++'."""
    alias = alias.strip()
    if not alias:
        return False
    short = len(alias) <= 2
    term = re.escape(alias if short else alias)
    pat = r"(?<![\w+#.])" + term + r"(?![\w+#])"
    return re.search(pat, text, 0 if short else re.I) is not None


def skill_aliases(item: str) -> list[str]:
    """'Node.js (backend)' -> ['node.js'];  'C / C++' -> ['c', 'c++']."""
    base = re.sub(r"\s*\(.*?\)\s*", " ", item).strip()
    return [n.strip().lower() for n in base.split(" / ") if n.strip()]


def posting_text(posting: dict | None) -> str:
    if not posting:
        return ""
    return f"{posting.get('title', '')}\n{posting.get('description', '') or ''}"


def wanted_terms(posting: dict | None, entries: list[dict]) -> set[str]:
    """The bank's own skill vocabulary that the posting mentions. Nothing is guessed: a term
    the bank does not hold can never be 'wanted'."""
    text = posting_text(posting)
    if not text.strip():
        return set()
    return {v for v in bank.vocabulary(entries) if mentions(v, text)}


def role_wanted_terms(entries: list[dict], role_type: str) -> set[str]:
    """For a role-type resume: the skills of every bullet tagged for that role type."""
    out: set[str] = set()
    for e in entries:
        for b in e["bullets"]:
            if role_type in bank.role_types(b["tags"]) or role_type in bank.role_types(e["tags"]):
                out |= bank.skill_tags(b["tags"])
    return out


def bullet_relevance(bullet: dict, entry: dict, wanted: set[str], role_type: str | None) -> int:
    terms = bank.skill_tags(bullet["tags"])
    terms |= {w for w in wanted if mentions(w, bullet["text"])}
    score = len(terms & wanted)
    if role_type and (role_type in bank.role_types(bullet["tags"])
                      or role_type in bank.role_types(entry["tags"])):
        score += 2
    return score


# --------------------------------------------------------------------------- duplicates

DUP_TOKEN_RE = re.compile(r"\b(?:\d[\d,.]*\s*(?:percent|stars?|%)?|[A-Z][A-Za-z.+#]{3,})\b")


def duplicate_claims(entries: list[dict]) -> list[str]:
    """Two selected bullets of ONE entry making the same distinctive claim.

    Distinctive = a number, or a capitalised technical token not at the start of the line
    (at position 0 a capital is grammar, not meaning). A token that opens a longer capitalised
    name ('Vercel' in 'Vercel AI SDK') names a different thing than the bare token. Compared
    only inside one entry: the same tool on two different projects is two true facts."""
    dups = []
    for entry in entries:
        seen: dict[str, str] = {}
        for bullet in entry["selected"]:
            words = bullet["text"].split()
            tokens = set()
            for i, raw in enumerate(words):
                if i == 0:
                    continue
                tok = raw.strip(".,;:()").strip()
                nxt = words[i + 1] if i + 1 < len(words) else ""
                compound = (not raw.endswith((".", ",", ";", ":", ")")) and nxt[:1].isupper())
                if tok and DUP_TOKEN_RE.fullmatch(tok) and not compound:
                    tokens.add(tok)
            for tok in tokens:
                if tok in seen and seen[tok] != bullet["id"]:
                    dups.append(f"{seen[tok]} and {bullet['id']} both claim {tok!r}")
                else:
                    seen.setdefault(tok, bullet["id"])
    return sorted(set(dups))


# --------------------------------------------------------------------------- selection


def select(entries: list[dict], wanted: set[str] | None = None, role_type: str | None = None,
           max_bullets: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Choose and order bullets. `entries` come from bank.load(); skill rows are ignored here.

    Returns (chosen, log). Each chosen entry carries `selected` (its bullets in bank order),
    `relevance` and `base_rank`. Sorted by section, then pinned first, then relevance, then
    the bank's own order, so output is stable."""
    wanted = {w.lower() for w in (wanted or set())}
    limits = {**MAX_BULLETS, **(max_bullets or {})}
    chosen, log = [], []
    for rank, entry in enumerate(e for e in entries if e["section"] in BODY_SECTIONS):
        bullets = entry["bullets"]
        always = [b for b in bullets if "always" in b["tags"]]
        optional = [b for b in bullets if "always" not in b["tags"]]
        scored = sorted(optional, key=lambda b: (-bullet_relevance(b, entry, wanted, role_type),
                                                 bullets.index(b)))
        room = max(0, limits.get(entry["section"], 3) - len(always))
        picked, skipped = list(always), []
        for b in scored:
            if len(picked) - len(always) >= room:
                break
            if duplicate_claims([{"selected": picked + [b]}]):
                skipped.append(b)
            else:
                picked.append(b)
        picked += skipped[:max(0, room - (len(picked) - len(always)))]
        picked.sort(key=lambda b: bullets.index(b))
        score = sum(bullet_relevance(b, entry, wanted, role_type) for b in bullets)
        if role_type and role_type in bank.role_types(entry["tags"]):
            score += 2
        chosen.append({**entry, "selected": picked, "relevance": score, "base_rank": rank,
                       "pinned": "pinned" in entry["tags"]})
        log.append({"entry": entry["id"], "relevance": score,
                    "included": [b["id"] for b in picked],
                    "dropped": [b["id"] for b in optional if b not in picked]})
    chosen.sort(key=lambda p: (SECTION_ORDER.index(p["section"]), not p["pinned"],
                               -p["relevance"], p["base_rank"]))
    return chosen, log


def drop_victim(entries: list[dict]) -> dict | None:
    """Which entry a one-page overflow removes: the least relevant one that is not Experience,
    not Education and not pinned. None when nothing may go."""
    droppable = [p for p in entries
                 if p["section"] not in ("experience", "education") and not p.get("pinned")]
    if not droppable:
        return None
    return min(droppable, key=lambda p: (p["relevance"], -p["base_rank"]))


def trim_target(entries: list[dict], floor: int = 2) -> dict | None:
    """Which entry gives up a bullet next, before any whole entry is removed. A bullet costs
    one line; an entry costs its heading and every bullet under it. Takes from the fullest
    entry, ties toward the least relevant. Never an 'always' bullet, never below `floor`."""
    cands = [p for p in entries
             if len(p["selected"]) > floor and any("always" not in b["tags"] for b in p["selected"])]
    if not cands:
        return None
    return max(cands, key=lambda p: (len(p["selected"]), -p["relevance"], -p["base_rank"]))


def take_bullet(target: dict) -> str | None:
    """Remove the last optional bullet from `target`. Returns its id, or None."""
    for i in range(len(target["selected"]) - 1, -1, -1):
        if "always" not in target["selected"][i]["tags"]:
            return target["selected"].pop(i)["id"]
    return None


def unused_inventory(entries: list[dict], chosen: list[dict]) -> list[str]:
    """Bank bullets that did NOT reach this resume, so inventory that never surfaces is seen."""
    used = {b["id"] for p in chosen for b in p["selected"]}
    return [b["id"] for e in entries if e["section"] in BODY_SECTIONS
            for b in e["bullets"] if b["id"] not in used]


def fit_step(chosen: list[dict]) -> str | None:
    """One step of overflow relief, applied in place. Returns what was removed, or None when
    nothing more may go. Order: a bullet from the fullest entry (floor 2), then the least
    relevant droppable entry while more than 3 remain, then thin below the floor.
    Never touches an Experience entry."""
    target = trim_target(chosen)
    if target is not None:
        taken = take_bullet(target)
        if taken:
            return f"dropped {taken}"
    if sum(1 for p in chosen if p["section"] != "education") > 3:
        victim = drop_victim(chosen)
        if victim is not None:
            chosen.remove(victim)
            return f"dropped entry {victim['id']}"
    target = trim_target(chosen, floor=1)
    if target is not None:
        taken = take_bullet(target)
        if taken:
            return f"dropped {taken}"
    return None


# --------------------------------------------------------------------------- skills


def _uses(bullet: dict, aliases: list[str]) -> bool:
    tags = {t.lower() for t in bullet["tags"]}
    return any(mentions(a, bullet["text"]) for a in aliases) or any(a in tags for a in aliases)


def pick_skills(entries: list[dict], chosen: list[dict], wanted: set[str] | None = None
                ) -> list[tuple[str, list[str]]]:
    """[(group label, [terms])] for this page. A term is eligible only if a bullet on this page
    uses it; the posting's asks rank first, page use breaks ties; each group is capped."""
    wanted = {w.lower() for w in (wanted or set())}
    page = [b for p in chosen for b in p["selected"]]
    groups: dict[str, list[tuple]] = {}
    order = 0
    for e in entries:
        if e["section"] != "skills" or not e["title"].strip():
            continue
        item = e["title"].strip()
        aliases = skill_aliases(item)
        order += 1
        used = sum(1 for b in page if _uses(b, aliases))
        if not used:
            continue
        asked = any(a in wanted for a in aliases)
        label = (e["org"] or "Skills").strip() or "Skills"
        groups.setdefault(label, []).append((-(10 * asked + min(used, 3)), order, item))
    out = []
    for label, items in groups.items():
        cap = SKILL_CAP_LANGUAGES if "language" in label.lower() else SKILL_CAP_OTHER
        out.append((label, [i for _, _, i in sorted(items)][:cap]))
    return out
