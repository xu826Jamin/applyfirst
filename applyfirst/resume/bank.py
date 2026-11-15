"""The experience bank: rows in the `experience` table, and the model resumes are built from.

Row shapes (all in one table, see schema.sql):

  entry   parent_id ''        a job, project, school, activity, or one skill term
  bullet  parent_id = entry   one line of text that may appear on a resume

Sections: experience | projects | education | skills | other.
Skill rows are entries with no bullets: `title` is the term, `org` is its group label
("Languages", "Frameworks and Tools"). Tags are a JSON list of lower-case strings; a tag
that starts with "role:" names a role type (a field from settings.search.fields), every
other tag is a skill or tool. A bullet tagged "always" is never trimmed by the one-page
fitter, an entry tagged "pinned" leads its section.

Only confirmed rows reach a resume. A bullet counts only when its entry is confirmed too.
"""
from __future__ import annotations

import hashlib
import json
import re

from .. import store

SECTIONS = ["experience", "projects", "education", "skills", "other"]
ROLE_PREFIX = "role:"
TEMPLATE_VERSION = "1"          # bump when the renderer changes: older files become stale

_ID_RE = re.compile(r"^E(\d+)$")


# --------------------------------------------------------------------------- helpers


def parse_tags(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(t) for t in raw]
    try:
        v = json.loads(raw or "[]")
        return [str(t) for t in v] if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def role_types(tags: list[str]) -> set[str]:
    return {t[len(ROLE_PREFIX):] for t in tags if t.startswith(ROLE_PREFIX)}


def skill_tags(tags: list[str]) -> set[str]:
    return {t.lower() for t in tags if not t.startswith(ROLE_PREFIX) and t not in ("always", "pinned", "needs-review")}


def _row(r: dict) -> dict:
    r = dict(r)
    r["tags"] = parse_tags(r.get("tags"))
    r["confirmed"] = int(r.get("confirmed") or 0)
    return r


def all_rows() -> list[dict]:
    rows = [_row(r) for r in store.rows("SELECT * FROM experience")]

    def key(r):
        sec = SECTIONS.index(r["section"]) if r["section"] in SECTIONS else len(SECTIONS)
        return (sec, r["position"], _idnum(r["id"]))
    return sorted(rows, key=key)


def _idnum(row_id: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", row_id))


def next_entry_id() -> str:
    n = 0
    for r in store.rows("SELECT id FROM experience"):
        m = _ID_RE.match(r["id"]) or re.match(r"^E(\d+)\.", r["id"])
        if m:
            n = max(n, int(m.group(1)))
    return f"E{n + 1}"


def next_bullet_id(parent_id: str) -> str:
    n = 0
    for r in store.rows("SELECT id FROM experience WHERE parent_id=?", (parent_id,)):
        m = re.search(r"\.b(\d+)$", r["id"])
        if m:
            n = max(n, int(m.group(1)))
    return f"{parent_id}.b{n + 1}"


def next_position(section: str, parent_id: str) -> int:
    r = store.one("SELECT MAX(position) AS m FROM experience WHERE section=? AND parent_id=?",
                  (section, parent_id))
    return (r["m"] + 1) if r and r["m"] is not None else 0


# --------------------------------------------------------------------------- reading


def load(confirmed_only: bool = True) -> list[dict]:
    """Entries with their bullets, in bank order.

    [{id, section, title, org, dates, tags, position, bullets: [{id, text, tags, position}]}]
    """
    rows = all_rows()
    entries = []
    for r in rows:
        if r["parent_id"]:
            continue
        if confirmed_only and not r["confirmed"]:
            continue
        entries.append({**r, "bullets": []})
    by_id = {e["id"]: e for e in entries}
    for r in rows:
        e = by_id.get(r["parent_id"]) if r["parent_id"] else None
        if e is None:
            continue
        if confirmed_only and not r["confirmed"]:
            continue
        if r["text"].strip():
            e["bullets"].append(r)
    for e in entries:
        e["bullets"].sort(key=lambda b: (b["position"], _idnum(b["id"])))
    return entries


def has_confirmed() -> bool:
    r = store.one("SELECT COUNT(*) AS n FROM experience WHERE confirmed=1")
    return bool(r and r["n"])


def fingerprint(extra: str = "") -> str:
    """A hash of every confirmed row, so a file built from an older bank is known stale."""
    rows = [(r["id"], r["parent_id"], r["section"], r["title"], r["org"], r["dates"], r["text"],
             sorted(r["tags"]), r["position"]) for r in all_rows() if r["confirmed"]]
    blob = json.dumps([rows, extra, TEMPLATE_VERSION], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def known_text(entries: list[dict] | None = None) -> list[str]:
    """Every string a resume may legitimately print as a claim: confirmed bullet text."""
    entries = load(True) if entries is None else entries
    return [b["text"] for e in entries for b in e["bullets"]]


def vocabulary(entries: list[dict]) -> set[str]:
    """Skill and tool terms the bank knows: skill rows plus every non-role tag."""
    vocab: set[str] = set()
    for e in entries:
        if e["section"] == "skills" and e["title"].strip():
            vocab.add(e["title"].strip().lower())
        vocab |= skill_tags(e["tags"])
        for b in e["bullets"]:
            vocab |= skill_tags(b["tags"])
    return {v for v in vocab if v}


# --------------------------------------------------------------------------- writing

_COLUMNS = ("section", "parent_id", "title", "org", "dates", "text", "tags", "confirmed", "position")


def add(row: dict) -> dict:
    """Insert one row. An entry gets an E<n> id, a bullet <parent>.b<n>. Returns the stored row."""
    section = row.get("section") or "other"
    if section not in SECTIONS:
        raise ValueError(f"section must be one of {', '.join(SECTIONS)}")
    parent = row.get("parent_id") or ""
    if parent:
        p = store.one("SELECT section FROM experience WHERE id=?", (parent,))
        if not p:
            raise ValueError(f"no entry {parent}")
        section = p["section"]
        rid = next_bullet_id(parent)
    else:
        rid = next_entry_id()
    pos = row.get("position")
    stored = {
        "id": rid, "parent_id": parent, "section": section,
        "title": str(row.get("title") or ""), "org": str(row.get("org") or ""),
        "dates": str(row.get("dates") or ""), "text": str(row.get("text") or ""),
        "tags": parse_tags(row.get("tags")),
        "confirmed": 1 if row.get("confirmed", 0) else 0,
        "position": int(pos) if pos is not None else next_position(section, parent),
    }
    store.upsert("experience", stored)
    return get(rid)


def get(row_id: str) -> dict | None:
    r = store.one("SELECT * FROM experience WHERE id=?", (row_id,))
    return _row(r) if r else None


def update(row_id: str, changes: dict) -> dict | None:
    cur = get(row_id)
    if cur is None:
        return None
    patch = {}
    for k in ("section", "title", "org", "dates", "text", "position"):
        if k in changes and changes[k] is not None:
            patch[k] = changes[k]
    if "tags" in changes and changes["tags"] is not None:
        patch["tags"] = parse_tags(changes["tags"])
    if "confirmed" in changes and changes["confirmed"] is not None:
        patch["confirmed"] = 1 if changes["confirmed"] else 0
    if "section" in patch and patch["section"] not in SECTIONS:
        raise ValueError(f"section must be one of {', '.join(SECTIONS)}")
    if patch:
        vals = {k: (json.dumps(v) if k == "tags" else v) for k, v in patch.items()}
        store.execute(f"UPDATE experience SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?",
                      (*vals.values(), row_id))
        if "section" in patch and not cur["parent_id"]:
            store.execute("UPDATE experience SET section=? WHERE parent_id=?", (patch["section"], row_id))
    return get(row_id)


def delete(row_id: str) -> bool:
    if get(row_id) is None:
        return False
    store.execute("DELETE FROM experience WHERE id=? OR parent_id=?", (row_id, row_id))
    return True


def confirm_all() -> int:
    n = (store.one("SELECT COUNT(*) AS n FROM experience WHERE confirmed=0") or {}).get("n", 0)
    store.execute("UPDATE experience SET confirmed=1 WHERE confirmed=0")
    return n


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def replace_unconfirmed(entries: list[dict]) -> list[dict]:
    """Store a fresh import. Unconfirmed rows from an earlier import are discarded; confirmed
    rows are never touched, and an imported bullet that repeats a confirmed one is skipped.

    `entries` is [{section, title, org, dates, tags, bullets: [{text, tags}]}].
    Returns the new rows (entries and bullets) as stored."""
    store.execute("DELETE FROM experience WHERE confirmed=0")
    have = {norm_text(r["text"]) for r in all_rows() if r["text"].strip()}
    have_entries = {(r["section"], norm_text(r["title"]), norm_text(r["org"]))
                    for r in all_rows() if not r["parent_id"]}
    out = []
    for e in entries:
        key = (e["section"], norm_text(e.get("title", "")), norm_text(e.get("org", "")))
        if key in have_entries and key != (e["section"], "", ""):
            continue
        bullets = [b for b in e.get("bullets", []) if norm_text(b.get("text", "")) not in have]
        if not bullets and e["section"] != "skills" and key in have_entries:
            continue
        row = add({"section": e["section"], "title": e.get("title", ""), "org": e.get("org", ""),
                   "dates": e.get("dates", ""), "tags": e.get("tags", []), "confirmed": 0})
        out.append(row)
        have_entries.add(key)
        for b in bullets:
            have.add(norm_text(b["text"]))
            out.append(add({"parent_id": row["id"], "text": b["text"], "tags": b.get("tags", []),
                            "confirmed": 0}))
    return out
