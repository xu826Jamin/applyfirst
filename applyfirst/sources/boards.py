"""The list of employer boards a sweep reads, and how it grows.

`boards.json` in this package is the seed list that ships with the tool. Boards a user's own
discovery finds are saved in their data folder (`boards.json` there), never in the install, so
the shipped list stays the same for everyone and a user's list survives an upgrade.

A board earns its place by returning postings. Board names are never guessed from a company
name: a made-up name that happens to resolve is often another company's board.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from .. import config, store
from .fetchers import FETCHERS, Ctx, board_key
from .net import FetchError, Http

SEED = Path(__file__).with_name("boards.json")

# Public directories of employer boards, read at run time. Each entry: ats, slug (or token), name,
# and for Workday wd + site. A directory that is down or has changed shape is skipped and
# reported; it is never a reason to fail the sweep.
DIRECTORIES = [
    "https://raw.githubusercontent.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships/main/data/companies.json",
]

_ATS_ALIASES = {"smartrecruiter": "smartrecruiters", "oracle": "oraclecloud", "oracle-cloud": "oraclecloud"}


def _clean(entry: dict) -> dict | None:
    ats = _ATS_ALIASES.get(str(entry.get("ats") or "").lower(), str(entry.get("ats") or "").lower())
    token = entry.get("token") or entry.get("slug")
    if ats not in FETCHERS or not token or not isinstance(token, str):
        return None
    b = {"ats": ats, "token": token.strip(), "company": str(entry.get("company") or entry.get("name") or token).strip()}
    for k in ("site", "wd", "oc_pod"):
        if entry.get(k):
            b[k] = str(entry[k])
    if ats == "workday" and not (b.get("site") and b.get("wd")):
        return None
    return b


def user_path() -> Path:
    return config.path("boards.json")


def load_seed() -> list[dict]:
    return [b for b in (_clean(e) for e in json.loads(SEED.read_text(encoding="utf-8"))) if b]


def load_user() -> list[dict]:
    p = user_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [b for b in (_clean(e) for e in data if isinstance(e, dict)) if b]


def load_all() -> list[dict]:
    """Seed plus the user's own, one entry per board."""
    seen, out = set(), []
    for b in load_seed() + load_user():
        k = board_key(b)
        if k not in seen:
            seen.add(k)
            out.append(b)
    return out


def save_user(boards: list[dict]) -> None:
    user_path().write_text(json.dumps(boards, ensure_ascii=False, indent=0), encoding="utf-8")


def counts() -> dict:
    """{ats: number of boards}, for the API."""
    by: dict[str, int] = {}
    for b in load_all():
        by[b["ats"]] = by.get(b["ats"], 0) + 1
    return dict(sorted(by.items()))


def add_board(board: dict) -> bool:
    """Remember a board the user's sweep proved. True if it was new."""
    b = _clean(board)
    if not b:
        return False
    have = {board_key(x) for x in load_all()}
    if board_key(b) in have:
        return False
    save_user(load_user() + [b])
    return True


def directory_candidates(http: Http) -> tuple[list[dict], list[str]]:
    """Boards named by the public directories that we do not already have, and notes on any
    directory that could not be read."""
    have = {board_key(b) for b in load_all()}
    out, notes, seen = [], [], set()
    for url in DIRECTORIES:
        host = urllib.parse.urlparse(url).hostname
        try:
            data = http.json(url)
        except FetchError as e:
            notes.append(f"{host}: {e}")
            continue
        entries = data.get("companies") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            notes.append(f"{host}: not a list of boards")
            continue
        for e in entries:
            b = _clean(e) if isinstance(e, dict) else None
            if b and board_key(b) not in have and board_key(b) not in seen:
                seen.add(board_key(b))
                out.append(b)
    return out, notes


def discover(run_id: str, http: Http | None = None, limit: int = 6000, workers: int = 16) -> str:
    """Grow the board list from the public directories. Each candidate is read once; one that
    returns at least one posting is kept."""
    from concurrent.futures import ThreadPoolExecutor

    http = http or Http()
    candidates, notes = directory_candidates(http)
    for n in notes:
        store.log(run_id, f"Board directory skipped: {n}")
    candidates = candidates[:limit]
    ctx = Ctx(http=http, terms=["intern"])      # a Workday board is probed with one cheap search
    store.log(run_id, f"Trying {len(candidates)} new boards")

    def probe(b: dict):
        try:
            return b, len(FETCHERS[b["ats"]](b, ctx).postings), None
        except FetchError as e:
            return b, 0, e.kind
        except Exception as e:      # a reader bug must not stop discovery
            return b, 0, f"error: {e}"

    kept, failed = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for b, n, err in pool.map(probe, candidates):
            if err:
                failed += 1
            elif n > 0:
                kept.append(b)
    if kept:
        save_user(load_user() + kept)
    msg = f"Tried {len(candidates)} boards, added {len(kept)} that have postings, {failed} could not be read."
    if notes:
        msg += f" {len(notes)} directory(ies) could not be reached."
    return msg
