"""One reader per applicant-tracking system.

Every reader takes a board (`{"ats", "token", "company", ...}`) and a `Ctx`, and returns a
`FetchResult`: the board's postings as plain dicts, and whether that list is the WHOLE board.
A reader that cannot read the board raises `FetchError`; it never returns an empty list to
mean "I could not read it", because the sweep would then treat every posting as gone.

A posting dict carries: job_id, title, location, url, apply_url, posted_at (ISO or ''),
description (plain text or ''), and optional hints: workplace, country_hint, slug, ref,
deadline. The sweep turns these into `postings` rows.
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable

from .net import FetchError, Http
from .util import parse_deadline, parse_posted, strip_html


@dataclass
class FetchResult:
    postings: list[dict]
    complete: bool = True      # False when the list is a slice (search terms, page cap)
    note: str = ""


@dataclass
class Ctx:
    http: Http
    terms: list[str] = field(default_factory=list)       # Workday search terms; [] = whole board
    countries: list[str] = field(default_factory=list)   # the user's wanted countries


def _q(token: str) -> str:
    """Tokens come from lists we do not control: never let one rewrite a URL path."""
    return urllib.parse.quote(str(token), safe="")


def _list(data: Any, key: str, what: str) -> list:
    items = data.get(key) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise FetchError(f"{what} did not return a list of postings", "bad-response")
    return items


def _posting(job_id, title, url, **kw) -> dict:
    p = {"job_id": str(job_id), "title": (title or "").strip(), "url": url or "",
         "apply_url": kw.pop("apply_url", None) or url or "", "location": "", "posted_at": "",
         "description": ""}
    p.update({k: v for k, v in kw.items() if v is not None})
    return p


# ------------------------------------------------------------------------------- Greenhouse

def greenhouse(board, ctx) -> FetchResult:
    data = ctx.http.json(f"https://boards-api.greenhouse.io/v1/boards/{_q(board['token'])}/jobs?content=true")
    out = []
    for j in _list(data, "jobs", "Greenhouse"):
        # first_published is when it went up; updated_at moves on every edit and would make an
        # old posting look new.
        out.append(_posting(
            j.get("id"), j.get("title"), j.get("absolute_url"),
            location=(j.get("location") or {}).get("name") or "",
            posted_at=parse_posted(j.get("first_published") or j.get("updated_at")),
            description=strip_html(j.get("content"))))
    return FetchResult(out)


# ------------------------------------------------------------------------------------ Lever

def lever(board, ctx) -> FetchResult:
    data = ctx.http.json(f"https://api.lever.co/v0/postings/{_q(board['token'])}?mode=json")
    out = []
    for j in _list(data, "postings" if isinstance(data, dict) else None, "Lever"):
        cats = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or strip_html(j.get("description"))]
        # The requirements and responsibilities live in `lists`, not in the description.
        for block in j.get("lists") or []:
            parts.append(f"{block.get('text') or ''}\n{strip_html(block.get('content'))}")
        parts.append(j.get("additionalPlain") or strip_html(j.get("additional")))
        locs = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
        out.append(_posting(
            j.get("id"), j.get("text"), j.get("hostedUrl"),
            apply_url=j.get("applyUrl"),
            location="; ".join(str(x) for x in locs),
            posted_at=parse_posted(j.get("createdAt")),
            description="\n\n".join(p.strip() for p in parts if p and p.strip()),
            workplace=j.get("workplaceType") or "",
            country_hint=(j.get("country") or "").upper() or None))
    return FetchResult(out)


# ------------------------------------------------------------------------------------ Ashby

def ashby(board, ctx) -> FetchResult:
    data = ctx.http.json(
        f"https://api.ashbyhq.com/posting-api/job-board/{_q(board['token'])}?includeCompensation=false")
    out = []
    for j in _list(data, "jobs", "Ashby"):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [
            (s.get("location") if isinstance(s, dict) else str(s)) or ""
            for s in j.get("secondaryLocations") or []]
        out.append(_posting(
            j.get("id"), j.get("title"), j.get("jobUrl"), apply_url=j.get("applyUrl"),
            location="; ".join(x for x in locs if x),
            posted_at=parse_posted(j.get("publishedAt")),
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
            workplace="remote" if j.get("isRemote") else (j.get("workplaceType") or "")))
    return FetchResult(out)


# ------------------------------------------------------------------------- SmartRecruiters

def smartrecruiters(board, ctx) -> FetchResult:
    base = f"https://api.smartrecruiters.com/v1/companies/{_q(board['token'])}/postings"
    out, offset, complete = [], 0, True
    for page in range(10):
        data = ctx.http.json(f"{base}?limit=100&offset={offset}")
        items = _list(data, "content", "SmartRecruiters")
        for j in items:
            loc = j.get("location") or {}
            where = ", ".join(x for x in (loc.get("city"), loc.get("region"),
                                          (loc.get("country") or "").upper()) if x)
            out.append(_posting(
                j.get("id"), j.get("name"), f"https://jobs.smartrecruiters.com/{_q(board['token'])}/{j.get('id')}",
                location=where, posted_at=parse_posted(j.get("releasedDate")),
                workplace="remote" if loc.get("remote") else "",
                country_hint=(loc.get("country") or "").upper() or None,
                ref=j.get("ref") or ""))
        total = data.get("totalFound") if isinstance(data, dict) else None
        offset += 100
        if len(items) < 100 or (isinstance(total, int) and offset >= total):
            break
    else:
        complete = False
    return FetchResult(out, complete=complete, note="" if complete else "stopped at 1,000 postings")


def smartrecruiters_body(board, posting, http) -> tuple[str, bool]:
    url = posting.get("ref") or (
        f"https://api.smartrecruiters.com/v1/companies/{_q(board['token'])}/postings/{_q(posting['job_id'])}")
    try:
        data = http.json(url)
    except FetchError as e:
        if e.status in (404, 410):
            return "", False
        raise
    sections = ((data or {}).get("jobAd") or {}).get("sections") or {}
    text = "\n\n".join(strip_html((s or {}).get("text")) for s in sections.values() if isinstance(s, dict))
    return text.strip(), True


# --------------------------------------------------------------------------------- Workable

def workable(board, ctx) -> FetchResult:
    data = ctx.http.json(
        f"https://apply.workable.com/api/v1/widget/accounts/{_q(board['token'])}?details=true")
    out = []
    for j in _list(data, "jobs", "Workable"):
        where = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        url = j.get("url") or j.get("shortlink") or j.get("application_url")
        out.append(_posting(
            j.get("shortcode"), j.get("title"), url, location=where,
            posted_at=parse_posted(j.get("published_on") or j.get("created_at")),
            description=strip_html(j.get("description")),
            workplace="remote" if j.get("telecommuting") else ""))
    return FetchResult(out)


# -------------------------------------------------------------------------------- Recruitee

_RECRUITEE_HOST = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def recruitee(board, ctx) -> FetchResult:
    slug = str(board["token"]).lower()
    if not _RECRUITEE_HOST.match(slug):
        raise FetchError("not a valid Recruitee name", "bad-response")
    data = ctx.http.json(f"https://{slug}.recruitee.com/api/offers/")
    out = []
    for j in _list(data, "offers", "Recruitee"):
        where = j.get("location") or ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        out.append(_posting(
            j.get("id") or j.get("slug"), j.get("title"), j.get("careers_url") or j.get("url"),
            location=where, posted_at=parse_posted(j.get("published_at") or j.get("created_at")),
            description=strip_html(j.get("description")),
            workplace="remote" if j.get("remote") else "",
            country_hint=(j.get("country_code") or "").upper() or None))
    return FetchResult(out)


# ---------------------------------------------------------------------------------- BambooHR

def bamboohr(board, ctx) -> FetchResult:
    slug = _q(board["token"])
    data = ctx.http.json(f"https://{slug}.bamboohr.com/careers/list")
    out = []
    for j in _list(data, "result", "BambooHR"):
        loc = j.get("location") or {}
        where = ", ".join(x for x in (loc.get("city"), loc.get("state")) if x) or j.get("locationName") or ""
        out.append(_posting(
            j.get("id"), j.get("jobOpeningName"), f"https://{slug}.bamboohr.com/careers/{j.get('id')}",
            location=where, posted_at=parse_posted(j.get("datePosted")),
            workplace="remote" if j.get("isRemote") else (j.get("locationType") or "")))
    return FetchResult(out)


def bamboohr_body(board, posting, http) -> tuple[str, bool]:
    slug = _q(board["token"])
    try:
        data = http.json(f"https://{slug}.bamboohr.com/careers/{_q(posting['job_id'])}/detail")
    except FetchError as e:
        if e.status in (404, 410):
            return "", False
        raise
    opening = (((data or {}).get("result") or {}).get("jobOpening")) or {}
    return strip_html(opening.get("description")), True


# --------------------------------------------------------------------------- Oracle Cloud

def oraclecloud(board, ctx) -> FetchResult:
    token, pod = _q(board["token"]), _q(board.get("oc_pod") or "ocs")
    site = board.get("site") or "CX_1"
    host = f"{token}.fa.{pod}.oraclecloud.com"
    out, offset, complete = [], 0, True
    for page in range(5):
        finder = f"findReqs;siteNumber={site},limit=200,offset={offset},sortBy=POSTING_DATES_DESC"
        url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
               f"?onlyData=true&expand=requisitionList.secondaryLocations&finder={urllib.parse.quote(finder, safe=';=,')}")
        data = ctx.http.json(url)
        items = _list(data, "items", "Oracle Cloud")
        reqs = (items[0].get("requisitionList") if items else None) or []
        for r in reqs:
            rid = r.get("Id")
            link = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}"
            out.append(_posting(rid, r.get("Title"), link, location=r.get("PrimaryLocation") or "",
                                posted_at=parse_posted(r.get("PostedDate"))))
        if len(reqs) < 200:
            break
    else:
        complete = False
    return FetchResult(out, complete=complete, note="" if complete else "stopped at 1,000 postings")


def oraclecloud_body(board, posting, http) -> tuple[str, bool]:
    token, pod = _q(board["token"]), _q(board.get("oc_pod") or "ocs")
    site = board.get("site") or "CX_1"
    url = (f"https://{token}.fa.{pod}.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
           f"?onlyData=true&finder=ByKey;Id={_q(posting['job_id'])},siteNumber={site}")
    try:
        data = http.json(url)
    except FetchError as e:
        if e.status in (404, 410):
            return "", False
        raise
    item = (((data or {}).get("items") or [{}])[0]) or {}
    return strip_html(item.get("ExternalDescriptionStr") or item.get("ShortDescriptionStr")), True


# ---------------------------------------------------------------------------------- Phenom

def phenom(board, ctx) -> FetchResult:
    """Phenom career sites. The token is the careers HOST (jobs.example.com). Phenom ignores a
    country filter, so this asks for the newest postings and leaves selection to the sweep; the
    list is never the whole board."""
    host = str(board["token"]).lower()
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        raise FetchError("not a valid careers host", "bad-response")
    out, seen = [], set()
    for term in (ctx.terms or [""]):
        payload = {"lang": "en_us", "deviceType": "desktop", "country": "us", "pageName": "search-results",
                   "ddoKey": "refineSearch", "sortBy": "Most recent", "subsearch": "", "from": 0,
                   "jobs": True, "counts": False, "size": 50, "clearAll": False, "keywords": term,
                   "global": True, "selected_fields": {}, "locationData": {}}
        data = ctx.http.post_json(f"https://{host}/widgets", payload)
        jobs = (((data or {}).get("refineSearch") or {}).get("data") or {}).get("jobs")
        if not isinstance(jobs, list):
            raise FetchError("the careers site did not answer like Phenom", "bad-response")
        for j in jobs:
            jid = j.get("jobId") or j.get("jobSeqNo")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            link = j.get("applyUrl") or f"https://{host}/job/{jid}"
            out.append(_posting(jid, j.get("title"), link, location=j.get("location") or j.get("cityStateCountry") or "",
                                posted_at=parse_posted(j.get("postedDate") or j.get("dateCreated")),
                                description=strip_html(j.get("descriptionTeaser")),
                                country_hint=(j.get("country") or "").upper()[:2] or None))
    return FetchResult(out, complete=False, note="newest 50 per search term")


# ---------------------------------------------------------------- Breezy, Pinpoint, Rippling

def breezy(board, ctx) -> FetchResult:
    data = ctx.http.json(f"https://{_q(board['token'])}.breezy.hr/json")
    out = []
    for j in _list(data, None, "Breezy"):
        loc = j.get("location") or {}
        where = loc.get("name") or ", ".join(x for x in (loc.get("city"), loc.get("state")) if x)
        country = (loc.get("country") or {}).get("name") if isinstance(loc.get("country"), dict) else ""
        out.append(_posting(
            j.get("id") or j.get("friendly_id") or j.get("url"), j.get("name"), j.get("url"),
            location=", ".join(x for x in (where, country) if x),
            posted_at=parse_posted(j.get("published_date")),
            workplace="remote" if loc.get("is_remote") else ""))
    return FetchResult(out)


def pinpoint(board, ctx) -> FetchResult:
    data = ctx.http.json(f"https://{_q(board['token'])}.pinpointhq.com/postings.json")
    out = []
    for j in _list(data, "data", "Pinpoint"):
        loc = j.get("location") or {}
        where = loc.get("name") or ", ".join(x for x in (loc.get("city"), loc.get("province")) if x)
        out.append(_posting(j.get("id") or j.get("url"), j.get("title"), j.get("url"), location=where,
                            posted_at=parse_posted(j.get("published_at")),
                            description=strip_html(j.get("description")),
                            deadline=parse_deadline(j.get("deadline_at")) or None))
    return FetchResult(out)


def rippling(board, ctx) -> FetchResult:
    data = ctx.http.json(f"https://api.rippling.com/platform/api/ats/v1/board/{_q(board['token'])}/jobs")
    out = []
    for j in _list(data, None, "Rippling"):
        loc = j.get("workLocation") or {}
        out.append(_posting(j.get("id") or j.get("url"), j.get("name"), j.get("url"),
                            location=loc.get("label") or ""))
    return FetchResult(out)


# ------------------------------------------------------------------------ Personio, Teamtailor

def personio(board, ctx) -> FetchResult:
    slug = _q(board["token"])
    body, host = "", ""
    last: FetchError | None = None
    for tld in ("de", "com"):
        host = f"{slug}.jobs.personio.{tld}"
        try:
            body = ctx.http.text(f"https://{host}/xml")
            break
        except FetchError as e:
            last = e
            if e.status != 404:
                raise
    else:
        raise last or FetchError("Personio board not found", "http404", 404)
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise FetchError("Personio did not return valid XML", "bad-response") from e
    out = []
    for pos in root.iter("position"):
        pid = (pos.findtext("id") or "").strip()
        offices = [pos.findtext("office") or ""] + [(o.text or "") for o in pos.iter("office") if o is not pos]
        desc = "\n\n".join(
            f"{(d.findtext('name') or '').strip()}\n{strip_html(d.findtext('value'))}"
            for d in pos.iter("jobDescription"))
        out.append(_posting(pid, pos.findtext("name"), f"https://{host}/job/{pid}",
                            location="; ".join(dict.fromkeys(o.strip() for o in offices if o.strip())),
                            posted_at=parse_posted(pos.findtext("createdAt")), description=desc.strip()))
    return FetchResult(out)


def teamtailor(board, ctx) -> FetchResult:
    body = ctx.http.text(f"https://{_q(board['token'])}.teamtailor.com/jobs.rss")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise FetchError("Teamtailor did not return a valid feed", "bad-response") from e
    out = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        cities = [e.text.strip() for e in item.iterfind(".//{*}city") if e.text]
        countries = [e.text.strip() for e in item.iterfind(".//{*}country") if e.text]
        where = ", ".join(x for x in (", ".join(dict.fromkeys(cities)), ", ".join(dict.fromkeys(countries))) if x)
        out.append(_posting(item.findtext("guid") or link, item.findtext("title"), link, location=where,
                            posted_at=parse_posted((item.findtext("pubDate") or "").strip()),
                            description=strip_html(item.findtext("description"))))
    return FetchResult(out)


# ------------------------------------------------------------------------------- registry

def _workday(board, ctx) -> FetchResult:
    from . import workday
    if not board.get("site"):
        raise FetchError("a Workday board needs its site name", "bad-response")
    return workday.fetch(board, ctx)


def _workday_body(board, posting, http):
    from . import workday
    return workday.fetch_body(board, posting, http)


FETCHERS: dict[str, Callable[[dict, Ctx], FetchResult]] = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
    "workable": workable, "workday": _workday, "recruitee": recruitee, "bamboohr": bamboohr,
    "oraclecloud": oraclecloud, "phenom": phenom, "breezy": breezy, "pinpoint": pinpoint,
    "personio": personio, "teamtailor": teamtailor, "rippling": rippling,
}

# Readers whose list has no posting text. The sweep calls these only for postings that are
# new, and counts a failure instead of filling the gap.
BODY_FETCHERS: dict[str, Callable[[dict, dict, Http], tuple[str, bool]]] = {
    "workday": _workday_body, "smartrecruiters": smartrecruiters_body,
    "bamboohr": bamboohr_body, "oraclecloud": oraclecloud_body,
}


def board_key(board: dict) -> str:
    return "|".join([board["ats"], str(board["token"]).lower(), str(board.get("site") or "")])
