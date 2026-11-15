"""Where the user's data lives, and the two documents that describe them.

Everything about a user is in their data home (default ~/.applyfirst, override with the
APPLYFIRST_HOME environment variable). Nothing personal is ever written inside the repo.

  profile.json    facts about the person (name, school, work authorization, links...)
  settings.json   choices about what to apply to and how
  secrets.json    mail password and similar; never shown back in full by the API
  applyfirst.sqlite  postings, applications, answers, runs (see store.py)
  resumes/        imported and generated resume files

Both documents are merged over the defaults below on load, so a new setting added in a
later version appears with its default instead of breaking older files.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- paths


def home() -> Path:
    p = Path(os.environ.get("APPLYFIRST_HOME") or Path.home() / ".applyfirst")
    p.mkdir(parents=True, exist_ok=True)
    (p / "resumes").mkdir(exist_ok=True)
    (p / "runs").mkdir(exist_ok=True)
    return p


def path(name: str) -> Path:
    return home() / name


# --------------------------------------------------------------------------- defaults

DEFAULT_PROFILE: dict[str, Any] = {
    "name": {"first": "", "last": "", "preferred": ""},
    "email": "",
    "phone": "",
    "location": {"city": "", "region": "", "country": "", "postal_code": ""},
    "links": {"linkedin": "", "github": "", "portfolio": "", "other": []},
    "education": [
        # {"school": "", "degree": "", "field": "", "start": "YYYY-MM", "end": "YYYY-MM",
        #  "gpa": "", "gpa_scale": "", "current": true}
    ],
    "work_authorization": {
        # country code -> {"authorized": true, "needs_sponsorship": false}
    },
    "citizenship": [],
    "languages": [
        # {"language": "English", "level": "Native"}
    ],
    "availability": {
        "earliest_start": "",          # YYYY-MM-DD
        "term_months": [],             # e.g. [4, 8, 12, 16] for co-op and internship terms
        "willing_to_relocate": True,
    },
    "salary": {"currency": "", "hourly_min": None, "annual_min": None},
    # Every demographic field is optional. "" means "decline to answer" on forms.
    "demographics": {
        "gender": "",
        "pronouns": "",
        "ethnicity": "",
        "disability": "",
        "veteran": "",
    },
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "search": {
        # Where the user wants to work. Countries are ISO codes; regions and cities narrow them.
        "countries": [],
        "regions": [],                 # e.g. ["Ontario", "British Columbia", "California"]
        "cities": [],
        "remote": "include",           # include | only | exclude
        # Career level: internship, co-op, new-grad, entry, mid, senior
        "levels": ["internship", "co-op", "new-grad"],
        # Fields: software, hardware, data-ml, quant, product, design, it-security, research,
        # mechanical, electrical, civil, business, finance, marketing, sales, operations, other
        "fields": ["software"],
        "include_keywords": [],
        "exclude_keywords": [],
        "exclude_companies": [],
        "start_terms": [],             # e.g. ["2027-01", "2027-05"]; empty = any
        "min_term_months": 0,
        "max_posting_age_days": 30,
        "skip_language_required": [],  # e.g. ["French"]: skip postings that require it
    },
    "sources": {
        "company_boards": True,        # Greenhouse, Lever, Ashby, Workday, SmartRecruiters and more
        "indeed": False,
        "glassdoor": False,
        "linkedin": False,
        "google_recent": False,
        "email_alerts": False,
        "school_board": {"enabled": False, "name": "", "url": ""},
        "sweep_interval_hours": 24,
    },
    "queue": {
        # newest | deadline | company | match
        "order_by": "newest",
        "then_by": "deadline",
        "daily_limit": 25,
    },
    "apply": {
        "mode": "review",              # review (approve each one) | auto (submit without asking)
        "review_first": 5,             # in auto mode, still review the first N
        "resume_tailoring": "by-role-type",   # one | by-role-type | per-job
        "cover_letters": "when-required",     # never | when-required | always
        "future_commitments": "yes",   # yes | literal  (relocation, start date, term, travel)
        "verify_resume_lines": True,   # every resume line must trace to the experience bank
        "browser": "chrome-extension", # chrome-extension (Claude in Chrome) | playwright
        "pace_seconds": 3,             # minimum gap between requests to one site
    },
    "tracker": {
        "email": {"enabled": False, "imap_host": "", "imap_port": 993, "username": "", "mailbox": "INBOX"},
        "sync_interval_hours": 24,
    },
    "schedule": {"run_daily": False, "time": "08:00"},
    "claude": {
        "command": "claude",
        "model": "sonnet",
        "max_turns_per_application": 60,
        "daily_budget_usd": 10,        # Claude spending cap per day; 0 = no cap
    },
    "alerts": {
        "desktop": True,               # a notification on this computer when new matches arrive
        "email": False,                # an email to yourself (uses the email settings below)
        "min_new": 1,                  # only alert when at least this many new matches
    },
}

# Which settings the interface shows with a warning, and the warning text.
WARNINGS: dict[str, str] = {
    "sources.linkedin": "LinkedIn restricts accounts it thinks are automated. Use at your own risk.",
    "sources.indeed": "Indeed may sign you out or block searches if it sees too many requests.",
    "sources.glassdoor": "Glassdoor may block searches if it sees too many requests.",
    "apply.mode": "Auto mode submits without showing you first. Some employers allow one application per role or per season.",
    "apply.verify_resume_lines": "With this off, generated resume lines are not checked against your experience.",
    "apply.pace_seconds": "Below about 3 seconds, job sites start refusing requests.",
    "claude.daily_budget_usd": "At 0 there is no cap: a large batch can use a lot of your Claude plan in one day.",
    "apply.browser":"The Playwright browser closes when Claude finishes, so in review mode the filled form is lost before you can submit it. Use Chrome for review mode.",
}


# --------------------------------------------------------------------------- load/save


def _merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = copy.deepcopy(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(over) if over is not None else copy.deepcopy(base)


def _load(name: str, default: dict) -> dict:
    p = path(name)
    if not p.exists():
        return copy.deepcopy(default)
    with open(p, encoding="utf-8") as f:
        return _merge(default, json.load(f))


def _save(name: str, data: dict) -> None:
    p = path(name)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def load_profile() -> dict:
    return _load("profile.json", DEFAULT_PROFILE)


def save_profile(data: dict) -> dict:
    merged = _merge(DEFAULT_PROFILE, data)
    _save("profile.json", merged)
    return merged


def load_settings() -> dict:
    return _load("settings.json", DEFAULT_SETTINGS)


def save_settings(data: dict) -> dict:
    merged = _merge(DEFAULT_SETTINGS, data)
    _save("settings.json", merged)
    return merged


def load_secrets() -> dict:
    return _load("secrets.json", {})


def save_secret(key: str, value: str) -> None:
    s = load_secrets()
    s[key] = value
    _save("secrets.json", s)
    try:
        os.chmod(path("secrets.json"), 0o600)
    except OSError:
        pass


def get(settings: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = settings
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def is_set_up() -> bool:
    p = load_profile()
    return bool(p["name"]["first"] and p["email"])
