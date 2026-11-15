"""Cover letters: written by Claude from the bank and the posting, checked before they are kept.

Every number and every capitalised name or tool in the body must occur in the bank, the posting
or the profile; the evidence the writer cites must point at real bank rows. A letter that fails
is given one retry with the problems listed, and is dropped (None) if it still fails, because a
letter that claims something untrue is worse than no letter.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path

from .. import claude, config, store
from . import bank, builder, provenance, render, style, tailor

SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "sentence": {"type": "string"},
            "bank_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["sentence", "bank_ids"]}},
    },
    "required": ["paragraphs", "evidence"],
}

PROMPT = """Write the body of a cover letter for this job application. 3 or 4 short paragraphs, plain and specific,
first person, under 250 words in total. No salutation and no sign-off (they are added for you).

HARD RULES
- Use ONLY facts from THE BANK below. Every number, employer, school, project and tool you mention must appear
  there. Do not invent, round up, or imply anything the bank does not say.
- You may name the company and role from THE POSTING, and say specific things about the work it describes.
  Take what you say about the work from the posting text only, never from general knowledge of the company.
- Skip stock phrases: no "passionate", "excited to join", "innovative", "cutting-edge", "perfect fit",
  "leverage", "mission" or "culture" with nothing specific behind it. Say what was built and what it did.
- For every sentence that states something about the applicant, list the bank row ids that support it in
  "evidence" (sentence + bank_ids).
{fix}
THE APPLICANT: {name}

THE BANK (id: text)
{bank}

THE POSTING
Company: {company}
Role: {title}
Location: {location}
{description}
"""


def _bank_block(entries: list[dict]) -> str:
    lines = []
    for e in entries:
        head = " | ".join(x for x in (e["title"], e["org"], e["dates"]) if x)
        if e["section"] == "skills":
            lines.append(f"{e['id']}: skill: {e['title']}")
            continue
        lines.append(f"{e['id']}: [{e['section']}] {head}")
        lines += [f"  {b['id']}: {b['text']}" for b in e["bullets"]]
    return "\n".join(lines)


def _evidence_problems(evidence: list, entries: list[dict]) -> list[str]:
    valid = {e["id"] for e in entries} | {b["id"] for e in entries for b in e["bullets"]}
    problems = []
    if not evidence:
        problems.append("the letter cites no bank rows as evidence")
    for item in evidence:
        for rid in (item or {}).get("bank_ids", []):
            if rid not in valid:
                problems.append(f"evidence cites {rid}, which is not a row in the bank")
    return sorted(set(problems))


def _write(posting: dict, profile: dict, paragraphs: list[str]) -> str:
    n = profile.get("name") or {}
    company = str(posting.get("company", "")).strip()
    header = [date.today().strftime("%B %d, %Y").replace(" 0", " "),
              f"Dear {company} Hiring Team," if company else "Dear Hiring Team,"]
    body = paragraphs + ["Sincerely,\n" + render.full_name(profile)]
    html = render.render_letter_html(profile, header, [p.replace("\n", " ") for p in body])
    base = builder.safe(n.get("preferred") or n.get("first") or "", n.get("last") or "") or "Applicant"
    tail = builder.safe(company, str(posting.get("title", "")), limit=60)
    d = builder.resumes_dir() / "letters"
    d.mkdir(parents=True, exist_ok=True)
    pdf = d / f"{base}_Cover_Letter_{tail}.pdf".replace("_.", ".")
    if render.find_browser():
        with tempfile.TemporaryDirectory(prefix="applyfirst-letter-") as tmp:
            src, out = os.path.join(tmp, "letter.html"), os.path.join(tmp, "letter.pdf")
            Path(src).write_text(html, encoding="utf-8")
            ok, _ = render.render_pdf(src, out)
            if ok:
                shutil.copyfile(out, pdf)
                return str(pdf)
    out = pdf.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    return str(out)


def cover_letter(posting: dict, run_id: str | None = None) -> str | None:
    """A cover letter PDF path for the posting, or None when the posting has no body (nothing
    specific to write about), Claude cannot be reached, or the letter would not stay true."""
    desc = str((posting or {}).get("description") or "").strip()
    if not desc:
        return None
    profile = config.load_profile()
    entries = bank.load(True)
    if not any(e["section"] != "skills" for e in entries):
        raise builder.BankEmpty(builder.EMPTY_MSG)
    log = (lambda m: store.log(run_id, m)) if run_id else (lambda m: None)

    fix, last_problems, data = "", [], None
    good: list[str] = []
    good_data: dict = {}
    for attempt in range(2):
        prompt = PROMPT.format(
            fix=fix, name=render.full_name(profile), bank=_bank_block(entries),
            company=posting.get("company", ""), title=posting.get("title", ""),
            location=posting.get("location", ""), description=desc[:9000])
        res = claude.run(prompt, run_id, json_schema=SCHEMA, max_turns=3, timeout=600)
        data = res.structured if res.ok else None
        if not isinstance(data, dict) or not isinstance(data.get("paragraphs"), list) or not data["paragraphs"]:
            log(f"cover letter: no usable answer from Claude ({res.error[:200]})")
            return None
        paras = [str(p).strip() for p in data["paragraphs"] if str(p).strip()]
        last_problems = (provenance.check_letter(paras, entries, posting, profile)
                         + _evidence_problems(data.get("evidence") or [], entries))
        notes = style.style_findings("\n\n".join(paras))
        if not last_problems:
            good, good_data = paras, data      # a true draft is kept even if a retry for style fails
            if not notes:
                break
        elif good:
            break
        issues = last_problems + [f"style: {n}" for n in notes]
        fix = ("\nYOUR LAST DRAFT HAD THESE PROBLEMS. Rewrite it and fix every one, using only the bank:\n- "
               + "\n- ".join(issues) + "\n")
        log(f"cover letter attempt {attempt + 1}: {len(issues)} problems")
    if not good:
        log("cover letter dropped, claims not traceable to the bank: " + "; ".join(last_problems[:5]))
        return None
    paras, data = good, good_data
    path = _write(posting, profile, paras)
    meta = {"letter": True, "built_at": store.now(), "evidence": data.get("evidence", []),
            "style_notes": style.style_findings("\n\n".join(paras)), "posting_id": posting.get("id", "")}
    Path(path).with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
