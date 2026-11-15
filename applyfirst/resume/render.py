"""HTML for a one-page resume, and HTML to PDF through a headless Chrome, Edge or Chromium.

The design is deliberately plain: one column, real text, standard headings on their own line,
no tables, no images, no icons, no text boxes. That is what applicant tracking systems parse.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HEADINGS = {
    "experience": "Experience", "projects": "Projects", "education": "Education",
    "skills": "Technical Skills", "other": "Activities and Other",
}

CSS = """
  @page { size: Letter; margin: 0.5in 0.6in; }
  * { box-sizing: border-box; }
  body { font-family: "Calibri","Carlito","Helvetica Neue",Arial,"Liberation Sans",sans-serif;
         font-size: 10pt; line-height: 1.22; color:#000; margin:0;
         font-variant-ligatures: none; -webkit-print-color-adjust: exact; }
  h1 { font-size: 19pt; letter-spacing:.02em; margin:0 0 2pt 0; font-weight:700; }
  .contact { font-size: 9.2pt; margin: 0 0 6pt 0; }
  h2 { font-size: 10pt; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
       margin: 7pt 0 2pt 0; padding-bottom:1pt; border-bottom:1px solid #000; }
  h3 { font-size: 10pt; font-weight:700; margin: 4.5pt 0 0 0; display:flex;
       justify-content:space-between; gap: 8pt; }
  h3 .d { font-weight:400; font-style:italic; white-space:nowrap; }
  .sub { font-size: 9.2pt; font-style:italic; margin:0 0 2pt 0; }
  ul { margin: 2pt 0 0 0; padding-left: 15pt; }
  li { margin: 0 0 1pt 0; }
  p { margin: 0 0 2pt 0; }
  a { color:#000; text-decoration:none; }
  .letter { font-size: 11pt; line-height: 1.35; }
  .letter p { margin: 0 0 9pt 0; }
"""


def esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _link_text(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url or "").rstrip("/")


def contact_parts(profile: dict) -> list[tuple[str, str]]:
    """[(text, href or '')] in the order they print."""
    loc = profile.get("location") or {}
    place = ", ".join(x for x in (loc.get("city"), loc.get("region")) if x)
    links = profile.get("links") or {}
    parts = [(place, ""), (profile.get("phone", ""), ""),
             (profile.get("email", ""), f"mailto:{profile.get('email')}" if profile.get("email") else "")]
    for key in ("linkedin", "github", "portfolio"):
        u = links.get(key) or ""
        if u:
            parts.append((_link_text(u), u if u.startswith("http") else f"https://{u}"))
    return [(t, h) for t, h in parts if t]


def full_name(profile: dict) -> str:
    n = profile.get("name") or {}
    first = n.get("preferred") or n.get("first") or ""
    return " ".join(x for x in (first, n.get("last") or "") if x).strip()


def profile_education(profile: dict) -> list[dict]:
    """Education from the profile, as entries, used only when the bank holds none."""
    out = []
    for i, e in enumerate(profile.get("education") or []):
        dates = " - ".join(x for x in (e.get("start", ""), "Present" if e.get("current") and not e.get("end")
                                       else e.get("end", "")) if x)
        degree = ", ".join(x for x in (e.get("degree", ""), e.get("field", "")) if x)
        if not (e.get("school") or degree):
            continue
        out.append({"id": f"P{i + 1}", "section": "education", "title": degree, "org": e.get("school", ""),
                    "dates": dates, "tags": [], "bullets": [], "selected": [], "relevance": 0,
                    "base_rank": i, "pinned": True})
    return out


def heading_parts(entry: dict) -> tuple[str, str, str, str]:
    """(left, sub, dates, link-free) pieces of an entry's heading line.

    Education leads with the school and puts the degree under it; every other section leads with
    the role or project name followed by the organisation."""
    if entry["section"] == "education":
        return entry["org"] or entry["title"], entry["title"] if entry["org"] else "", entry["dates"], ""
    left = ", ".join(x for x in (entry["title"], entry["org"]) if x)
    return left, "", entry["dates"], ""


def structural_strings(profile: dict, chosen: list[dict], skills: list[tuple[str, list[str]]]) -> list[str]:
    """Every non-bullet string the template may print: headings, contact line, entry headings,
    skill terms. Provenance tells a CLAIM (a bullet) from STRUCTURE with this list."""
    out = [full_name(profile)] + [t for t, _ in contact_parts(profile)] + list(HEADINGS.values())
    out += [profile.get("phone", ""), profile.get("email", "")]
    for e in chosen:
        out += [e["title"], e["org"], e["dates"]] + list(heading_parts(e)[:3])
    for label, items in skills:
        out += [label] + items
    return [s for s in out if s and len(s.strip()) > 1]


def render_html(profile: dict, chosen: list[dict], skills: list[tuple[str, list[str]]],
                education_first: bool = False) -> str:
    name = full_name(profile) or "Resume"
    out = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
           f"<title>{esc(name)} - Resume</title>", f"<style>{CSS}</style>", "</head>", "<body>",
           f"<h1>{esc(name)}</h1>"]
    bits = []
    for text, href in contact_parts(profile):
        bits.append(f'<a href="{esc(href)}">{esc(text)}</a>' if href else esc(text))
    if bits:
        out.append('<p class="contact">' + " &nbsp;|&nbsp; ".join(bits) + "</p>")

    def emit(section: str) -> None:
        members = [p for p in chosen if p["section"] == section]
        if not members:
            return
        out.append(f"<h2>{HEADINGS[section]}</h2>")
        for e in members:
            left, sub, dates, _ = heading_parts(e)
            d = f'<span class="d">{esc(dates)}</span>' if dates else ""
            if left or d:
                out.append(f"<h3><span>{esc(left)}</span>{d}</h3>")
            if sub:
                out.append(f'<p class="sub">{esc(sub)}</p>')
            if e["selected"]:
                out.append("<ul>")
                out.extend(f"  <li>{esc(b['text'])}</li>" for b in e["selected"])
                out.append("</ul>")

    def emit_skills() -> None:
        if not skills:
            return
        out.append(f"<h2>{HEADINGS['skills']}</h2>")
        for label, items in skills:
            out.append(f"<p><strong>{esc(label)}:</strong> {esc(', '.join(items))}</p>")

    order = (["education", "experience", "projects"] if education_first
             else ["experience", "projects", "education"])
    for s in order:
        emit(s)
    emit_skills()
    emit("other")
    out += ["</body>", "</html>"]
    return "\n".join(out)


def render_letter_html(profile: dict, header_lines: list[str], paragraphs: list[str]) -> str:
    name = full_name(profile) or "Cover letter"
    out = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
           f"<title>{esc(name)} - Cover Letter</title>", f"<style>{CSS}</style>", "</head>",
           '<body class="letter">', f"<h1>{esc(name)}</h1>"]
    bits = [esc(t) for t, _ in contact_parts(profile)]
    if bits:
        out.append('<p class="contact">' + " &nbsp;|&nbsp; ".join(bits) + "</p>")
    out.append("<p>&nbsp;</p>")
    for line in header_lines:
        out.append(f"<p>{esc(line)}</p>")
    for para in paragraphs:
        out.append(f"<p>{esc(para)}</p>")
    out += ["</body>", "</html>"]
    return "\n".join(out)


def estimate_lines(chosen: list[dict], skills: list[tuple[str, list[str]]]) -> float:
    """A rough count of printed lines, used to fit the page when no browser can measure it."""
    n = 4.0
    seen = set()
    for e in chosen:
        if e["section"] not in seen:
            seen.add(e["section"])
            n += 2
        n += 1.4 + (1 if e["section"] == "education" and e["title"] and e["org"] else 0)
        n += sum(max(1, math.ceil(len(b["text"]) / 100)) for b in e["selected"])
    if skills:
        n += 2 + len(skills)
    return n


PAGE_LINES = 58.0        # measured: a Letter page holds about 59 to 66 on this estimate


# --------------------------------------------------------------------------- browser


def browser_candidates() -> list[str]:
    env = os.environ.get("APPLYFIRST_BROWSER")
    out = [env] if env else []
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    out += [
        rf"{pf}\Google\Chrome\Application\chrome.exe",
        rf"{pf86}\Google\Chrome\Application\chrome.exe",
        rf"{local}\Google\Chrome\Application\chrome.exe",
        rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
        rf"{pf}\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "microsoft-edge", "microsoft-edge-stable", "chrome", "msedge"):
        w = shutil.which(name)
        if w:
            out.append(w)
    return out


def find_browser() -> str | None:
    for p in browser_candidates():
        if p and os.path.exists(p):
            return p
    return None


NO_BROWSER_NOTE = ("No Chrome, Edge or Chromium was found on this computer, so the resume was saved "
                   "as an HTML file instead of a PDF. Install Chrome or Edge (or set APPLYFIRST_BROWSER "
                   "to its path) to get a PDF.")


def render_pdf(html_path: str, pdf_path: str) -> tuple[bool, str]:
    browser = find_browser()
    if not browser:
        return False, NO_BROWSER_NOTE
    html_path, pdf_path = os.path.abspath(html_path), os.path.abspath(pdf_path)
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    url = Path(html_path).as_uri()
    # A throwaway profile: with the user's own Chrome already open, a headless launch on the
    # default profile hands off to that window and exits without printing anything.
    with tempfile.TemporaryDirectory(prefix="applyfirst-chrome-") as prof:
        cmd = [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
               "--disable-extensions", f"--user-data-dir={prof}", f"--print-to-pdf={pdf_path}", url]
        if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(2, "--no-sandbox")
        try:
            subprocess.run(cmd, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            if not os.path.exists(pdf_path):
                return False, "The browser did not finish printing the PDF in time."
        except OSError as e:
            return False, f"Could not start the browser: {e}"
    if not os.path.exists(pdf_path):
        return False, "The browser ran but produced no PDF."
    return True, ""


def page_count(pdf_path: str) -> int:
    import pypdf
    return len(pypdf.PdfReader(pdf_path).pages)


def pdf_text(pdf_path: str) -> str:
    """Text as a parser would read it. Empty string when nothing can be extracted."""
    try:
        import pypdf
        return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(pdf_path).pages)
    except Exception:  # noqa: BLE001  a corrupt file reads as empty, and the caller says so
        return ""
