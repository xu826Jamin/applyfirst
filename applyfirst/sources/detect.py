"""Which applicant-tracking system does a link belong to?

`parse_job_url` turns a posting link into the board it lives on and the posting's id on that
board, for the systems `fetchers` can read. `vendor_of` names the systems that have no reader
(iCIMS, Taleo and so on): the link is still stored, tagged with the system, so the apply step
knows what form it will meet.
"""
from __future__ import annotations

import re
import urllib.parse

from . import workday

# Words that appear as the first path part of a board URL but are never a board name.
ASSET_TOKENS = {"cdn", "assets", "static", "content", "www", "app", "media", "img", "js", "css",
                "embed", "jobs", "careers", "api"}

_TOKEN = r"([A-Za-z0-9][A-Za-z0-9._-]*)"

# (ats, regex over "host/path"); the first group is the board name, the second the posting id.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(rf"^(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?{_TOKEN}/jobs/(\d+)", re.I)),
    ("greenhouse", re.compile(rf"^(?:job-)?boards(?:\.eu)?\.greenhouse\.io/embed/job_app\?for={_TOKEN}&token=(\d+)", re.I)),
    ("lever", re.compile(rf"^jobs(?:\.eu)?\.lever\.co/{_TOKEN}/([0-9a-f-]{{20,}})", re.I)),
    ("ashby", re.compile(rf"^jobs\.ashbyhq\.com/{_TOKEN}/([0-9a-f-]{{20,}})", re.I)),
    ("smartrecruiters", re.compile(rf"^(?:jobs|careers)\.smartrecruiters\.com/{_TOKEN}/(\d+)", re.I)),
    ("workable", re.compile(rf"^apply\.workable\.com/{_TOKEN}/j/([A-Za-z0-9]+)", re.I)),
    ("recruitee", re.compile(r"^([a-z0-9][a-z0-9-]*)\.recruitee\.com/o/([A-Za-z0-9-]+)", re.I)),
    ("bamboohr", re.compile(r"^([a-z0-9][a-z0-9-]*)\.bamboohr\.com/careers/(\d+)", re.I)),
    ("breezy", re.compile(r"^([a-z0-9][a-z0-9-]*)\.breezy\.hr/p/([A-Za-z0-9-]+)", re.I)),
    ("pinpoint", re.compile(r"^([a-z0-9][a-z0-9-]*)\.pinpointhq\.com/en/postings/([A-Za-z0-9-]+)", re.I)),
    ("personio", re.compile(r"^([a-z0-9][a-z0-9-]*)\.jobs\.personio\.(?:de|com)/job/(\d+)", re.I)),
    ("teamtailor", re.compile(r"^([a-z0-9][a-z0-9-]*)\.teamtailor\.com/jobs/([A-Za-z0-9-]+)", re.I)),
    ("rippling", re.compile(rf"^ats\.rippling\.com/{_TOKEN}/jobs/([A-Za-z0-9-]+)", re.I)),
]

# Systems we can name but have no reader for.
_VENDORS: list[tuple[str, re.Pattern]] = [
    ("icims", re.compile(r"\.icims\.com", re.I)),
    ("taleo", re.compile(r"\.taleo\.net", re.I)),
    ("successfactors", re.compile(r"successfactors\.(?:com|eu)|\.sapsf\.", re.I)),
    ("eightfold", re.compile(r"\.eightfold\.ai", re.I)),
    ("avature", re.compile(r"\.avature\.net", re.I)),
    ("jobvite", re.compile(r"jobs\.jobvite\.com", re.I)),
    ("brassring", re.compile(r"brassring\.com", re.I)),
    ("ultipro", re.compile(r"ultipro\.com|ukg\.com", re.I)),
    ("phenom", re.compile(r"\.phenompeople\.com", re.I)),
    ("oraclecloud", re.compile(r"\.oraclecloud\.com", re.I)),
    ("workday", re.compile(r"\.myworkdayjobs\.com|\.myworkdaysite\.com", re.I)),
]


def _host_path(url: str) -> str:
    p = urllib.parse.urlparse(url.strip())
    return f"{(p.hostname or '').lower()}{p.path}" + (f"?{p.query}" if p.query else "")


def parse_job_url(url: str):
    """(board dict, job_id) for a link on a system we can read, else None."""
    wd = workday.parse_url(url)
    if wd:
        board, path = wd
        return {**board, "company": board["token"]}, path[-72:]
    hp = _host_path(url)
    for ats, rx in _PATTERNS:
        m = rx.match(hp)
        if m:
            token, job_id = m.group(1), m.group(2)
            if token.lower() in ASSET_TOKENS:
                continue
            return {"ats": ats, "token": token, "company": token}, job_id
    return None


def vendor_of(url: str) -> str:
    """The name of the system a link runs on, or ''."""
    host = (urllib.parse.urlparse(url.strip()).hostname or "").lower()
    for ats, rx in _VENDORS:
        if rx.search(host):
            return ats
    parsed = parse_job_url(url)
    return parsed[0]["ats"] if parsed else ""
