"""Build one-page resumes from the confirmed experience bank.

build / build_detailed   one resume for a role type, a posting, or neither
resume_for               the right resume for a posting, following apply.resume_tailoring
build_all                one resume per field in settings.search.fields
verify                   read a PDF back and check every line against the bank

A file is only reused when the bank, the profile and the template are exactly what built it,
so editing a bullet makes every older resume stale and the next request rebuilds it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .. import config, store
from . import bank, provenance, render, tailor


class BankEmpty(ValueError):
    """There is nothing confirmed to build from."""


EMPTY_MSG = ("Your experience bank has no confirmed lines yet. Import your resume, look the lines over "
             "and confirm them, then build.")


@dataclass
class BuildResult:
    path: str
    kind: str                       # pdf | html
    pages: int = 1
    problems: list[str] = field(default_factory=list)       # lines not traceable to the bank
    ats_problems: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    trims: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)
    note: str = ""
    reused: bool = False

    @property
    def clean(self) -> bool:
        return self.kind == "pdf" and self.pages == 1 and not (self.problems or self.ats_problems or self.duplicates)


# --------------------------------------------------------------------------- paths


def resumes_dir() -> Path:
    d = config.path("resumes")
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe(*parts: str, limit: int = 70) -> str:
    raw = "_".join(p for p in parts if p)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw)[:limit].strip("_")


def target_path(profile: dict, role_type: str | None, posting: dict | None, ext: str = "pdf") -> Path:
    n = profile.get("name") or {}
    base = safe(n.get("preferred") or n.get("first") or "", n.get("last") or "") or "Resume"
    if posting:
        tail = safe(str(posting.get("company", "")), str(posting.get("title", "")), limit=60)
        return resumes_dir() / f"{base}_Resume_{tail}.{ext}" if tail else resumes_dir() / f"{base}_Resume.{ext}"
    if role_type:
        d = resumes_dir() / "by-role" / safe(role_type, limit=40)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{base}_Resume.{ext}"
    return resumes_dir() / f"{base}_Resume.{ext}"


def _fingerprint(profile: dict, role_type: str | None, posting: dict | None) -> str:
    keep = {k: profile.get(k) for k in ("name", "email", "phone", "location", "links", "education")}
    extra = json.dumps({"p": keep, "role": role_type,
                        "posting": tailor.posting_text(posting) + str((posting or {}).get("field", ""))},
                       sort_keys=True, ensure_ascii=False)
    return bank.fingerprint(extra)


def _sidecar(path: Path) -> Path:
    return path.with_suffix(".json")


def read_meta(path: Path) -> dict:
    try:
        return json.loads(_sidecar(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_stale(path: Path) -> bool:
    """True when the file was built from a bank, profile or template that has since changed."""
    meta = read_meta(path)
    if not meta.get("fingerprint"):
        return True
    profile = config.load_profile()
    posting = meta.get("posting") if meta.get("posting") else None
    return meta.get("fingerprint") != _fingerprint(profile, meta.get("role_type"), posting)


# --------------------------------------------------------------------------- building


def _education_first(profile: dict, entries: list[dict]) -> bool:
    """Students lead with education; people with work history lead with it."""
    for e in profile.get("education") or []:
        if e.get("current"):
            return True
    return any(re.search(r"expected|present|current|202[6-9]|20[3-9]\d", e["dates"], re.I)
               for e in entries if e["section"] == "education")


def build_detailed(role_type: str | None = None, posting: dict | None = None,
                   reuse: bool = False) -> BuildResult:
    profile = config.load_profile()
    if not render.full_name(profile):
        raise ValueError("Add your name in Setup first; it heads the resume and names the file.")
    entries = bank.load(True)
    if not any(e["section"] != "skills" for e in entries):
        raise BankEmpty(EMPTY_MSG)
    settings = config.load_settings()
    verify_on = bool(config.get(settings, "apply.verify_resume_lines", True))
    fp = _fingerprint(profile, role_type, posting)
    pdf_target = target_path(profile, role_type, posting, "pdf")
    html_target = pdf_target.with_suffix(".html")

    if reuse:
        for p in (pdf_target, html_target):
            meta = read_meta(p)
            if p.exists() and meta.get("fingerprint") == fp and not meta.get("problems"):
                return BuildResult(str(p), meta.get("kind", "pdf"), meta.get("pages", 1),
                                   meta.get("problems", []), meta.get("ats_problems", []),
                                   meta.get("duplicates", []), meta.get("trims", []),
                                   meta.get("unused", []), meta.get("note", ""), reused=True)

    # What the posting (or role type) asks for, from the bank's own vocabulary only.
    role = role_type or ((posting or {}).get("field") or None)
    wanted = tailor.wanted_terms(posting, entries) if posting else set()
    if role and not wanted:
        wanted = tailor.role_wanted_terms(entries, role)
    chosen, log = tailor.select(entries, wanted, role)
    if not any(e["section"] == "education" for e in chosen):
        chosen += render.profile_education(profile)
        chosen.sort(key=lambda p: tailor.SECTION_ORDER.index(p["section"]))
    edu_first = _education_first(profile, entries)

    browser = render.find_browser()
    trims: list[str] = []
    pages, note, kind, out_path = 1, "", "pdf", pdf_target
    if browser:
        # A big bank would cost one browser run per trimmed line. Cut the obvious excess by
        # estimate first (generously, so nothing is over-trimmed), then let the browser decide.
        while render.estimate_lines(chosen, tailor.pick_skills(entries, chosen, wanted)) > render.PAGE_LINES * 1.12:
            step = tailor.fit_step(chosen)
            if step is None:
                break
            trims.append(step)
    with tempfile.TemporaryDirectory(prefix="applyfirst-build-") as tmp:
        tmp_html = os.path.join(tmp, "resume.html")
        tmp_pdf = os.path.join(tmp, "resume.pdf")
        html = ""
        for _ in range(200):
            skills = tailor.pick_skills(entries, chosen, wanted)
            html = render.render_html(profile, chosen, skills, edu_first)
            if browser:
                Path(tmp_html).write_text(html, encoding="utf-8")
                ok, err = render.render_pdf(tmp_html, tmp_pdf)
                if not ok:
                    note, kind = err, "html"
                    break
                pages = render.page_count(tmp_pdf)
                over = pages > 1
            else:
                kind, note = "html", render.NO_BROWSER_NOTE
                over = render.estimate_lines(chosen, skills) > render.PAGE_LINES
            if not over:
                break
            step = tailor.fit_step(chosen)
            if step is None:
                break
            trims.append(step)
        if kind == "pdf":
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp_pdf, out_path)
            if html_target.exists():
                html_target.unlink()
                _sidecar(html_target).unlink(missing_ok=True)
        else:
            out_path = html_target
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html, encoding="utf-8")
            if pdf_target.exists():          # a stale PDF must not outlive the bank it was built from
                pdf_target.unlink()

    skills = tailor.pick_skills(entries, chosen, wanted)
    headings = [render.HEADINGS[s] for s in ("education", "experience", "projects", "skills", "other")
                if (s == "skills" and skills) or any(p["section"] == s for p in chosen)]
    res = BuildResult(str(out_path), kind, pages if kind == "pdf" else 1, trims=trims, note=note,
                      duplicates=tailor.duplicate_claims(chosen),
                      unused=tailor.unused_inventory(entries, chosen))
    if kind == "pdf":
        if verify_on:
            res.problems = provenance.verify_pdf(str(out_path), entries, profile, chosen)
        res.ats_problems = provenance.ats_problems(str(out_path), profile, headings)
        if res.pages > 1:
            res.problems.append("The resume does not fit on one page even after trimming.")
    meta = {"fingerprint": fp, "role_type": role_type, "kind": kind, "pages": res.pages,
            "built_at": store.now(), "problems": res.problems, "ats_problems": res.ats_problems,
            "duplicates": res.duplicates, "trims": trims, "unused": res.unused, "note": note,
            "verified": verify_on, "selection": log,
            "chosen": {p["id"]: [b["id"] for b in p["selected"]] for p in chosen},
            "posting": ({"title": posting.get("title", ""), "description": posting.get("description", ""),
                         "field": posting.get("field", ""), "company": posting.get("company", "")}
                        if posting else None),
            "sections": [p["section"] + ":" + p["id"] for p in chosen]}
    _sidecar(out_path).write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def build(role_type: str | None = None, posting: dict | None = None) -> str:
    """Pick lines from the confirmed bank, render one page, return the PDF path (the HTML path,
    with the reason in the sidecar, when no browser is installed)."""
    return build_detailed(role_type, posting).path


def verify(pdf_path: str) -> list[str]:
    """Problems found reading a resume PDF back; an empty list means every line traces to the bank."""
    entries = bank.load(True)
    if not any(e["section"] != "skills" for e in entries):
        return [EMPTY_MSG]
    if not Path(pdf_path).exists():
        return [f"No such file: {pdf_path}"]
    return provenance.verify_pdf(pdf_path, entries, config.load_profile())


def role_for(posting: dict | None, settings: dict) -> str | None:
    fields = list(config.get(settings, "search.fields", []) or [])
    field_ = (posting or {}).get("field") or ""
    if field_ and (not fields or field_ in fields):
        return field_
    return fields[0] if fields else (field_ or None)


def resume_for(posting: dict, settings: dict) -> str:
    """The resume to attach to a posting, following apply.resume_tailoring:
    one (a single resume), by-role-type (one per field), per-job (selection per posting)."""
    mode = config.get(settings, "apply.resume_tailoring", "by-role-type")
    if mode == "per-job":
        return build_detailed(None, posting, reuse=True).path
    if mode == "one":
        return build_detailed(None, None, reuse=True).path
    return build_detailed(role_for(posting, settings), None, reuse=True).path


def build_all(settings: dict | None = None) -> list[BuildResult]:
    """One resume per field in settings.search.fields (by-role-type), or the single resume."""
    settings = settings or config.load_settings()
    if config.get(settings, "apply.resume_tailoring", "by-role-type") != "by-role-type":
        return [build_detailed(None, None, reuse=True)]
    fields = config.get(settings, "search.fields", []) or []
    return [build_detailed(f, None, reuse=True) for f in fields] or [build_detailed(None, None, reuse=True)]


def list_files() -> list[dict]:
    root = resumes_dir()
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".pdf", ".html"):
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith("imports/"):
            continue
        meta = read_meta(p)
        out.append({"name": rel, "kind": p.suffix.lower()[1:], "size": p.stat().st_size,
                    "modified": int(p.stat().st_mtime), "stale": (is_stale(p) if meta and not meta.get("letter") else None),
                    "problems": (meta.get("problems") or []) + (meta.get("ats_problems") or [])})
    return out
