"""Sources that are read through the user's own signed-in browser.

Indeed, Glassdoor, LinkedIn, Google's recent-postings search, job-alert emails and a school's
job board have no public API. Each one is off until the user turns it on, and each is read by
one Claude Code run that drives the browser the user already uses (Claude in Chrome, or the
bundled Playwright profile, whichever `apply.browser` says), at the pace `apply.pace_seconds`
sets. The run returns rows as JSON; `normalise_rows` turns them into postings.

Rules every prompt carries: read only, never click Apply, never sign in or out, and when a site
answers "too many requests" stop that search and hand back what was collected. A refusal is
slowed down for, not routed around.
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse

from .. import claude, config
from . import detect
from .util import normalise_url, parse_age_text, parse_posted

NAMES = ("indeed", "glassdoor", "linkedin", "google_recent", "email_alerts", "school_board")
MAX_SEARCHES = 12

_FIELD_WORDS = {
    "software": "software developer", "hardware": "hardware engineer", "data-ml": "data science",
    "quant": "quantitative developer", "product": "product manager", "design": "designer",
    "it-security": "security analyst", "research": "research assistant", "mechanical": "mechanical engineer",
    "electrical": "electrical engineer", "civil": "civil engineer", "business": "business analyst",
    "finance": "finance analyst", "marketing": "marketing", "sales": "sales", "operations": "operations",
}
_LEVEL_WORDS = {"internship": "intern", "co-op": "co-op", "new-grad": "new grad", "entry": "junior"}

_INDEED_HOSTS = {"CA": "ca.indeed.com", "GB": "uk.indeed.com", "AU": "au.indeed.com", "IN": "in.indeed.com",
                 "DE": "de.indeed.com", "FR": "fr.indeed.com", "IE": "ie.indeed.com"}

ROWS_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "company": {"type": "string"}, "location": {"type": "string"},
            "url": {"type": "string"}, "job_key": {"type": "string"},
            "posted": {"type": "string"}, "description": {"type": "string"}}, "required": ["title", "company"]}},
        "stopped": {"type": "string"},
    },
    "required": ["rows"],
}


def enabled(settings: dict) -> list[str]:
    """Browser sources the user switched on, in a stable order."""
    s = settings.get("sources") or {}
    out = []
    for name in NAMES:
        v = s.get(name)
        if name == "school_board":
            if isinstance(v, dict) and v.get("enabled") and v.get("url"):
                out.append(name)
        elif v:
            out.append(name)
    return out


def search_queries(settings: dict) -> list[tuple[str, str]]:
    """(search words, place) pairs, newest-first, capped. Places come from the user's cities,
    then regions, then countries; remote-only users search "remote"."""
    s = settings.get("search") or {}
    levels = [_LEVEL_WORDS[l] for l in (s.get("levels") or []) if l in _LEVEL_WORDS] or [""]
    fields = [_FIELD_WORDS[f] for f in (s.get("fields") or []) if f in _FIELD_WORDS] or [""]
    kws = [k for k in (s.get("include_keywords") or []) if k][:2]
    places = (s.get("cities") or []) or (s.get("regions") or []) or [
        {"CA": "Canada", "US": "United States", "GB": "United Kingdom"}.get(c, c) for c in (s.get("countries") or [])]
    if s.get("remote") == "only":
        places = ["remote"]
    places = places or [""]
    out: list[tuple[str, str]] = []
    for place in places:
        for f in fields:
            for l in levels:
                words = " ".join(x for x in (f, l) if x).strip()
                if words:
                    out.append((words, place))
        for k in kws:
            out.append((k, place))
    seen, uniq = set(), []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq[:MAX_SEARCHES]


def _indeed_host(settings: dict) -> str:
    for c in (settings.get("search") or {}).get("countries") or []:
        if c.upper() in _INDEED_HOSTS:
            return _INDEED_HOSTS[c.upper()]
    return "www.indeed.com"


def _age_days(settings: dict) -> int:
    n = (settings.get("search") or {}).get("max_posting_age_days") or 3
    return max(1, min(int(n), 3))


COMMON = """You are collecting job postings for a job search tool. Use the browser that is already
open; it is signed in as the user where that matters. Read only: never click Apply, never submit
a form, never sign in, sign out, or change any setting.
Wait about {pace} seconds between page loads. If a site shows "too many requests", a captcha, or
a security check, STOP that search, do not retry or work around it, and put one plain sentence in
"stopped". Return every posting you collected so far.
Return JSON only: {{"rows": [{{"title","company","location","url","job_key","posted","description"}}]}}.
"posted" is the site's own age text ("2 days ago", "24h"), copied as written. Leave a field empty
when the page does not show it; never guess one. Skip sponsored and promoted duplicates.
"""


def build_prompt(name: str, settings: dict) -> str:
    pace = (settings.get("apply") or {}).get("pace_seconds") or 3
    head = COMMON.format(pace=pace)
    queries = search_queries(settings)
    qlist = "\n".join(f"- {q} | {p or 'anywhere'}" for q, p in queries)
    days = _age_days(settings)
    if name == "indeed":
        host = _indeed_host(settings)
        return head + f"""
Source: Indeed ({host}). Run these searches (words | place), at most {len(queries)} searches and at most
about 28 page loads in total:
{qlist}
Search URL: https://{host}/jobs?q=<words>&l=<place>&sort=date&fromage={days}  (newest first, last {days} days).
Read at most 3 result pages per search. The results are embedded in the page as JSON at
window.mosaic.providerData["mosaic-provider-jobcards"] (fields jobkey, title, company, formattedLocation,
pubDate); use that when you can read it, otherwise read the visible cards. Put the Indeed jobkey in "job_key".
"""
    if name == "glassdoor":
        return head + f"""
Source: Glassdoor job search. Run these searches (words | place), newest first, last {days} days:
{qlist}
Read at most 3 result pages per search. The posting age is the last line of each card ("24h", "2d").
"""
    if name == "linkedin":
        return head + f"""
Source: LinkedIn Jobs (signed-in browser). Run these searches (words | place), newest first, last {days} days:
{qlist}
Read at most 2 result pages per search. Do not open profiles, send messages or connection requests,
or use Easy Apply. Stop at the first warning or check LinkedIn shows.
"""
    if name == "google_recent":
        hosts = " OR ".join(f"site:{h}" for h in (
            "boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "myworkdayjobs.com", "apply.workable.com"))
        return head + f"""
Source: Google search restricted to the last 24 hours (Tools, Any time, Past 24 hours). For each
(words | place) below search: ({hosts}) <words> <place>
{qlist}
Read the first 2 result pages. "url" is the posting link itself, not a Google redirect.
"""
    if name == "email_alerts":
        return head + """
Source: the user's job-alert emails. Open their webmail in the browser, find job-alert emails from
the last 3 days (Indeed, Glassdoor, LinkedIn, Google, company career alerts), and list every posting
in them. For each, "url" is the posting link; if the email only has a tracking link, open it and
use the page it lands on. Do not reply to, delete, archive or label any email.
"""
    if name == "school_board":
        sb = (settings.get("sources") or {}).get("school_board") or {}
        label = sb.get("name") or "the school's job board"
        return head + f"""
Source: {label}, at {sb.get('url')}. Open it and list every posting it shows that is open now, across
all pages. If it asks the user to sign in and they are not signed in, stop and say so in "stopped".
"""
    raise ValueError(f"unknown browser source: {name}")


# ----------------------------------------------------------------------------- rows to postings

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref$|refid|trk|tk$|from$|campaign|vjs$|advn$|adid)", re.I)


def clean_url(url: str, source: str = "", job_key: str = "") -> str:
    """The posting's own link with tracking removed. Indeed's identity is ?jk=, so an Indeed link
    is rebuilt from the job key and never loses it."""
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return ""
    p = urllib.parse.urlparse(u)
    host = (p.hostname or "").lower()
    q = urllib.parse.parse_qs(p.query)
    if "indeed." in host:
        key = job_key or (q.get("jk") or q.get("vjk") or [""])[0]
        return f"https://{host}/viewjob?jk={key}" if key else ""
    if "linkedin.com" in host:
        m = re.search(r"/jobs/view/(?:[^/?]*-)?(\d+)", p.path)
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}/" if m else ""
    keep = [(k, v) for k, vs in q.items() if not _TRACKING.match(k) for v in vs]
    return urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", urllib.parse.urlencode(keep), ""))


def normalise_rows(source: str, rows: list, settings: dict | None = None) -> tuple[list[dict], int]:
    """(posting dicts shaped like the fetchers', number of rows dropped). A row without a title,
    company or usable link is dropped and counted, never patched up."""
    out, dropped, seen = [], 0, set()
    for r in rows or []:
        if not isinstance(r, dict):
            dropped += 1
            continue
        title = str(r.get("title") or "").strip()
        company = str(r.get("company") or "").strip()
        key = str(r.get("job_key") or "").strip()
        url = clean_url(str(r.get("url") or ""), source, key)
        if source == "indeed" and not url and key:
            url = f"https://{_indeed_host(settings or {})}/viewjob?jk={key}"
        if not (title and company and url):
            dropped += 1
            continue
        ident = key if source == "indeed" and key else hashlib.sha1(normalise_url(url).encode()).hexdigest()[:16]
        if (source, ident) in seen:
            continue
        seen.add((source, ident))
        out.append({
            "job_id": ident, "title": title, "company": company, "url": url, "apply_url": url,
            "location": str(r.get("location") or "").strip(),
            "posted_at": parse_posted(r.get("posted")) or parse_age_text(str(r.get("posted") or "")),
            "description": str(r.get("description") or "").strip(),
            "vendor": detect.vendor_of(url),
        })
    return out, dropped


def collect(name: str, settings: dict, run_id: str) -> tuple[list[dict], str]:
    """Run one browser source. Returns (postings, a plain-language note, '' when all went well)."""
    if not claude.available():
        return [], "Claude Code is not installed, so this source was skipped."
    prompt = build_prompt(name, settings)
    res = claude.run(prompt, run_id, browser=(settings.get("apply") or {}).get("browser") or "chrome-extension",
                     json_schema=ROWS_SCHEMA, max_turns=80)
    if not res.ok and not res.structured:
        return [], res.error or "The browser run did not finish."
    data = res.structured if isinstance(res.structured, dict) else {}
    rows, dropped = normalise_rows(name, data.get("rows") or [], settings)
    notes = []
    if data.get("stopped"):
        notes.append(str(data["stopped"]))
    if dropped:
        notes.append(f"{dropped} rows were missing a title, company or link")
    if not res.ok:
        notes.append(res.error or "the run ended early")
    return rows, "; ".join(notes)
