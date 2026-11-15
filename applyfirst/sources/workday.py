"""Workday career sites (any tenant.wdN.myworkdayjobs.com).

Workday is the one big ATS with no shared API host: every employer is its own server, and the
search endpoint has quirks worth knowing before reading this file:

* A page holds at most 20 postings (asking for more is a 400).
* `searchText` is fuzzy and OR-ranked, so a search for "intern" also returns unrelated roles.
  Titles are filtered by the sweep's intake gate, not here.
* A query is clamped at offset 2000: a big board reports total 2000 and answers every offset
  past it with the same page. The clamp is detected from the facet counts in the same response
  (they describe the whole board) and recovered by re-asking once per value of the facet that
  partitions the board most finely. That detection and split come from the career-ops project.
* The country facet below is Canada's id on the tenants we measured; a tenant that rejects it
  (400/404/422) is asked again without it.
* Posting bodies are not in the list; each is a separate request, made only for postings that
  are new (see `fetch_body`).

The clamp detection and facet choice (`true_total_from_facets`, `clamp_note`,
`choose_split_facet`, and the split constants) are adapted from career-ops, providers/workday.mjs.

    MIT License

    Copyright (c) career-ops contributors

    Permission is hereby granted, free of charge, to any person obtaining a copy of this
    software and associated documentation files (the "Software"), to deal in the Software
    without restriction, including without limitation the rights to use, copy, modify,
    merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to the following
    conditions: the above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.
"""
from __future__ import annotations

import re

from .net import FetchError
from .util import parse_posted, strip_html

PAGE = 20                       # Workday refuses a bigger page
MAX_PAGES = 100                 # per query; the server clamps at offset 2000 = 100 pages
PAGE_BUDGET = 500               # requests for one board in one sweep, however its facets fan out
OFFSET_CEILING = 2000
MAX_SPLIT_DEPTH = 2             # (values of facet A) x (values of facet B) cleared every tenant measured
MAX_SPLIT_SLICES = 100          # bounds one facet with hundreds of tiny values
CANADA_FACET = {"locationCountry": ["a30a87ed25634629aa6c3958aa2b91ea"]}


# ----------------------------------------------------------------- clamp detection and split

def _facet_coverage(facet):
    values = facet.get("values") if isinstance(facet, dict) else None
    if not isinstance(values, list):
        values = []
    total, counted = 0, 0
    for v in values:
        if not isinstance(v, dict):
            continue
        count = v.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            continue
        total += count
        counted += 1
    return total if counted > 0 else None


def true_total_from_facets(facets):
    """Board size according to the facets, or None. Each facet partitions the same board, so the
    largest facet sum under-reports least."""
    best = None
    for facet in facets if isinstance(facets, list) else []:
        coverage = _facet_coverage(facet)
        if coverage is not None and (best is None or coverage > best):
            best = coverage
    return best


def clamp_note(total, facets):
    """A note when `total` looks clamped at the offset ceiling, else None."""
    if total != OFFSET_CEILING:
        return None
    true_total = true_total_from_facets(facets)
    if true_total is None or true_total <= total:
        return None
    return (f"reported total is exactly {total} but its facets sum to {true_total}: "
            f"the board is clamped at the {OFFSET_CEILING}-offset ceiling")


def choose_split_facet(facets, exclude=()):
    """The facet to split a clamped query on: the one whose largest slice is smallest (that
    slice is the one most at risk of still being clamped), ties toward more values. Values need
    a string id (group headers have none) and a non-negative integer count; a facet with fewer
    than two usable values is not a partition."""
    skip = set(exclude)
    best = None
    for facet in facets if isinstance(facets, list) else []:
        if not isinstance(facet, dict):
            continue
        param = facet.get("facetParameter")
        if not isinstance(param, str) or not param or param in skip:
            continue
        values = [v for v in (facet.get("values") or [])
                  if isinstance(v, dict) and isinstance(v.get("id"), str) and v.get("id")
                  and isinstance(v.get("count"), int) and not isinstance(v.get("count"), bool)
                  and v.get("count") >= 0]
        if len(values) < 2:
            continue
        largest = max(v["count"] for v in values)
        if (best is None or largest < best["largest"]
                or (largest == best["largest"] and len(values) > len(best["values"]))):
            best = {"facetParameter": param, "values": values, "largest": largest}
    if best is None:
        return None
    return {"facetParameter": best["facetParameter"], "values": best["values"]}


# ----------------------------------------------------------------------------- the crawl

def host_of(board: dict) -> str:
    wd = board.get("wd") or "wd1"
    return f"{board['token']}.{wd}.myworkdayjobs.com"


def _search_url(board: dict) -> str:
    return f"https://{host_of(board)}/wday/cxs/{board['token']}/{board['site']}/jobs"


def _paginate(http, url, term, applied, max_pages):
    postings, total, facets, page = [], None, [], 0
    while page < max_pages:
        data = http.post_json(url, {"appliedFacets": applied, "limit": PAGE,
                                    "offset": page * PAGE, "searchText": term})
        if not isinstance(data, dict):
            raise FetchError("Workday answered with something that is not a search result",
                             "bad-response")
        if page == 0:
            total = data.get("total")
            facets = data.get("facets") or []
        posts = data.get("jobPostings") or []
        postings.extend(posts)
        page += 1
        if len(posts) < PAGE:
            break
        if isinstance(total, int) and page * PAGE >= total:
            break
    return postings, total, facets, page


def _crawl_term(http, url, term, use_country, budget, notes):
    """One search term on one tenant, past the clamp when there is one."""
    state = {"country": use_country}

    def run(applied, max_pages):
        try:
            return _paginate(http, url, term, applied, max_pages)
        except FetchError as e:
            if state["country"] and applied and e.status in (400, 404, 422):
                state["country"] = False       # this tenant does not take the country facet
                return _paginate(http, url, term, {}, max_pages)
            raise

    root = dict(CANADA_FACET) if state["country"] else {}
    postings, total, facets, pages = run(root, MAX_PAGES)
    budget[0] += pages
    seen, out = set(), []

    def absorb(items):
        for job in items:
            path = job.get("externalPath") or ""
            if path and path not in seen:
                seen.add(path)
                out.append(job)

    absorb(postings)
    clamped = clamp_note(total, facets)
    if clamped:
        notes.append(clamped)
        spent = [0]
        base_excluded = ["locationCountry"] if state["country"] else []

        def split(result_facets, applied, depth, excluded):
            if depth >= MAX_SPLIT_DEPTH:
                return
            facet = choose_split_facet(result_facets, exclude=excluded)
            if not facet:
                return
            for value in facet["values"]:
                if spent[0] >= MAX_SPLIT_SLICES or budget[0] >= PAGE_BUDGET:
                    break
                spent[0] += 1
                nxt = dict(applied)
                nxt[facet["facetParameter"]] = [value["id"]]
                try:
                    sp, st, sf, pg = run(nxt, MAX_PAGES)
                except FetchError:
                    continue                   # one dead slice must not abandon the rest
                budget[0] += pg
                absorb(sp)
                if clamp_note(st, sf):
                    split(sf, nxt, depth + 1, excluded + [facet["facetParameter"]])

        split(facets, root, 0, base_excluded)
    return out


def fetch(board: dict, ctx):
    """Every posting on one Workday site that matches the search terms (all of them when the
    user's levels give no term)."""
    from .fetchers import FetchResult
    http = ctx.http
    url = _search_url(board)
    terms = list(ctx.terms) or [""]
    use_country = [c.upper() for c in (ctx.countries or [])] == ["CA"]
    budget, notes, jobs, seen = [0], [], [], set()
    for term in terms:
        if budget[0] >= PAGE_BUDGET:
            notes.append("page budget reached")
            break
        for job in _crawl_term(http, url, term, use_country, budget, notes):
            path = job.get("externalPath") or ""
            if path not in seen:
                seen.add(path)
                jobs.append(job)
    base = f"https://{host_of(board)}/en-US/{board['site']}"
    out = []
    for job in jobs:
        path = job["externalPath"]
        out.append({
            "job_id": path[-72:],
            "title": job.get("title") or "",
            "location": job.get("locationsText") or "",
            "url": base + path,
            "apply_url": base + path,
            "posted_at": parse_posted(job.get("postedOn") or ""),
            "description": "",
            "slug": path,
            "ref": path,
        })
    # A search by term is not the whole board, so absence from it proves nothing.
    return FetchResult(out, complete=(terms == [""]), note="; ".join(notes))


def fetch_body(board: dict, posting: dict, http) -> tuple[str, bool]:
    """(description text, still_open). A 404 or canApply False means the posting is closed."""
    path = posting.get("ref") or ""
    if not path:
        return "", True
    url = f"https://{host_of(board)}/wday/cxs/{board['token']}/{board['site']}{path}"
    try:
        data = http.json(url)
    except FetchError as e:
        if e.status in (404, 410):
            return "", False
        raise
    info = (data or {}).get("jobPostingInfo") or {}
    if info.get("canApply") is False:
        return "", False
    return strip_html(info.get("jobDescription") or ""), True


_URL_RE = re.compile(r"^https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)(/job/[^?#]*)",
                     re.I)


def parse_url(url: str):
    """A public Workday job URL to (board, path), or None."""
    m = _URL_RE.match(url or "")
    if not m:
        return None
    tenant, wd, site, path = m.groups()
    return {"ats": "workday", "token": tenant.lower(), "wd": wd.lower(), "site": site}, path


def fetch_one(board: dict, path: str, http) -> dict | None:
    """One posting from its detail page, for a link the user pasted. None when it is closed."""
    url = f"https://{host_of(board)}/wday/cxs/{board['token']}/{board['site']}{path}"
    try:
        data = http.json(url)
    except FetchError as e:
        if e.status in (404, 410):
            return None
        raise
    info = (data or {}).get("jobPostingInfo") or {}
    if not info or info.get("canApply") is False:
        return None
    base = f"https://{host_of(board)}/en-US/{board['site']}"
    where = info.get("location") or ""
    extra = [x for x in info.get("additionalLocations") or [] if isinstance(x, str)]
    return {
        "job_id": path[-72:], "title": info.get("title") or "", "location": "; ".join([where] + extra if where else extra),
        "url": base + path, "apply_url": info.get("externalUrl") or base + path,
        "posted_at": parse_posted(info.get("startDate") or info.get("postedOn") or ""),
        "description": strip_html(info.get("jobDescription") or ""), "slug": path, "ref": path,
    }
