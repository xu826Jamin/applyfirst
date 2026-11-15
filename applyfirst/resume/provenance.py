"""Checks that run on the finished artifact, from outside the thing that made it.

verify_pdf     every line of a resume PDF traces to a confirmed bank row (or is template structure)
check_letter   every factual claim in a cover letter traces to the bank or the posting
ats_problems   the PDF survives the plain text extraction an applicant tracking system does
"""
from __future__ import annotations

import re
import unicodedata

from . import render, tailor

SEP = "\x00"


def norm(text: str) -> str:
    """Normalise both sides of a comparison the same way, so the check tests provenance and
    not typography: ligatures and odd spaces folded, a line-wrap space after a hyphen removed
    ('ten- problem' vs 'ten-problem'), case ignored (headings are upper-cased by CSS)."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("­", "").replace("•", " ").replace("●", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"-\s+", "-", text)
    return text.lower().strip()


def _remove(chunks: list[str], text: str) -> str:
    out = text
    for chunk in sorted({norm(c) for c in chunks if c and norm(c)}, key=len, reverse=True):
        out = re.sub(r"(?<!\w)" + re.escape(chunk) + r"(?!\w)", SEP, out)
    return out


def verify_pdf(pdf_path: str, bank_entries: list[dict], profile: dict,
               selected: list[dict] | None = None) -> list[str]:
    """Problems found reading `pdf_path` back. Empty list means every line traces to the bank.

    Runs against the PDF, not the in-memory model, so a template bug that injected prose
    would be caught here rather than trusted away. With `selected` (the entries a build chose)
    it also asserts every chosen bullet really is on the page."""
    raw = render.pdf_text(pdf_path)
    text = norm(raw)
    if not text:
        return ["Could not read any text from the PDF, so its lines cannot be checked."]
    problems = []
    if selected:
        for e in selected:
            for b in e["selected"]:
                if norm(b["text"])[:90] not in text:
                    problems.append(f"{b['id']}: a chosen line is missing from the PDF")
    known = [b["text"] for e in bank_entries for b in e["bullets"]]
    for e in bank_entries:
        known += [e["title"], e["org"], e["dates"]] + list(render.heading_parts(e)[:3])
    known += list(render.HEADINGS.values())
    known += [render.full_name(profile), profile.get("phone", ""), profile.get("email", "")]
    known += [t for t, _ in render.contact_parts(profile)]
    for p in render.profile_education(profile):
        known += [p["title"], p["org"], p["dates"]]
    residual = _remove(known, text)
    for run in residual.split(SEP):
        words = re.sub(r"[\s|,:.;()\-/&@+•·–—]+", " ", run).strip()
        if len(re.sub(r"\W", "", words)) >= 8:
            problems.append(f"text on the PDF that is not in your experience bank: {words[:90]!r}")
    return problems


# --------------------------------------------------------------------------- letters

_MONTHS = ("January February March April May June July August September October November "
           "December Monday Tuesday Wednesday Thursday Friday Saturday Sunday").split()
_NUM_RE = re.compile(r"\b\d[\d,.]*\d\b|\b\d\b")
_CAP_RE = re.compile(r"\b[A-Z][A-Za-z0-9.+#]{2,}\b")


def _corpus(bank_entries: list[dict], posting: dict | None, profile: dict) -> str:
    parts = [b["text"] for e in bank_entries for b in e["bullets"]]
    for e in bank_entries:
        parts += [e["title"], e["org"], e["dates"]] + list(e["tags"])
    parts.append(tailor.posting_text(posting))
    if posting:
        parts += [str(posting.get("company", "")), str(posting.get("location", ""))]
    parts.append(render.full_name(profile))
    loc = profile.get("location") or {}
    parts += [str(v) for v in loc.values()]
    for ed in profile.get("education") or []:
        parts += [str(v) for v in ed.values()]
    return "\n".join(p for p in parts if p)


def check_letter(paragraphs: list[str], bank_entries: list[dict], posting: dict | None,
                 profile: dict) -> list[str]:
    """Claims in the letter body that appear nowhere in the bank, the posting or the profile.

    A claim is a number, or a capitalised name or term in mid-sentence (a tool, a company, a
    school). Both must occur in the allowed text. This catches an invented figure, employer
    or technology; it cannot judge a sentence's meaning, which is why the writer is also told
    to use only what the bank says."""
    corpus = _corpus(bank_entries, posting, profile)
    corpus_l = corpus.lower()
    corpus_nums = {n.rstrip(".,") for n in _NUM_RE.findall(corpus)}
    corpus_words = set(re.findall(r"[a-z0-9.+#]+", corpus_l))
    problems = []
    for para in paragraphs:
        for n in _NUM_RE.findall(para):
            if n.rstrip(".,") not in corpus_nums:
                problems.append(f"the number {n} is not in your experience or the posting")
        for sent in re.split(r"(?<=[.!?])\s+", para):
            words = sent.split()
            for i, raw in enumerate(words):
                if i == 0:
                    continue
                tok = raw.strip(".,;:()\"'!?")
                if not _CAP_RE.fullmatch(tok) or tok in _MONTHS:
                    continue
                low = tok.lower()
                if low in corpus_words or re.search(r"(?<![\w])" + re.escape(low) + r"(?![\w])", corpus_l):
                    continue
                problems.append(f"{tok!r} is not in your experience, the posting or your profile")
    return sorted(set(problems))


# --------------------------------------------------------------------------- applicant tracking

MIN_LINES = 5
MAX_LINE_CHARS = 400


def ats_problems(pdf_path: str, profile: dict, headings: list[str]) -> list[str]:
    """Plain-text extraction checks, the way a naive parser walks the page.

    A check that could not run reports itself as a problem rather than passing silently."""
    text = render.pdf_text(pdf_path)
    if len(text.strip()) < 100:
        return ["The PDF has almost no extractable text (it may be an image), so tracking systems cannot read it."]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    low = [ln.lower() for ln in lines]
    problems = []
    for h in headings:
        if h.lower() not in low:
            merged = next((ln for ln in lines if ln.lower().startswith(h.lower())
                           and len(ln) > len(h) + 3), None)
            problems.append(f"the heading {h!r} does not stand on its own line"
                            + (f" (it runs into {merged[:50]!r})" if merged else ""))
    flat = text.lower()
    if render.full_name(profile) and render.full_name(profile).lower() not in flat:
        problems.append("your name is missing from the extracted text")
    if profile.get("email") and profile["email"].lower() not in flat:
        problems.append("your email is missing from the extracted text")
    digits = re.sub(r"\D", "", profile.get("phone", ""))
    if digits and digits not in re.sub(r"\D", "", text):
        problems.append("your phone number is missing from the extracted text")
    if len(lines) < MIN_LINES:
        problems.append(f"only {len(lines)} lines survive extraction; the content collapsed")
    longest = max(lines, key=len)
    if len(longest) > MAX_LINE_CHARS:
        problems.append(f"one extracted line is {len(longest)} characters; bullets fused into a block")
    return problems
