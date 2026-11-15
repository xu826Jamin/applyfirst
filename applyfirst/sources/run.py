"""The sweep: read every enabled source, store what is new, close what is gone.

Order of a sweep:
 1. read every employer board in parallel (threads only fetch; every database write happens in
    the calling thread, because the store shares one connection);
 2. keep the postings that fit the user's levels and countries, and store the new ones;
 3. fetch posting text for the new ones whose board list carries none;
 4. read the browser sources the user switched on;
 5. close postings a fully read board no longer lists, and check the few that have no board;
 6. mark duplicates, then hand every new posting to the filters.

Nothing is guessed: a board that cannot be read is counted and left as it was, a posting with no
text keeps an empty description, and a country that cannot be read stays blank.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from .. import config, store
from . import boards as boards_mod
from . import browser, dedupe, detect, liveness, locations, workday
from .fetchers import BODY_FETCHERS, FETCHERS, Ctx, board_key
from .net import FetchError, Http
from .util import company_key, normalise_url, parse_posted, strip_html

WORKERS = 24
MAX_BODIES = 400            # posting texts fetched one by one per sweep
MAX_LIVENESS_CHECKS = 60    # page checks for postings that have no board, per sweep
RECHECK_DAYS = 3
EMPTY_ANSWER_GUARD = 5      # a board that lists nothing but held this many before is left alone

EARLY = re.compile(
    r"\b(intern|interns|internship|internships|co-?ops?|stagiaires?|apprentice|apprenticeship|trainee|"
    r"new[- ]?grad(?:uate)?s?|graduate\s+(?:program|programme|engineer|developer|analyst|scheme|role|software)|"
    r"university\s+(?:grad|graduate|student)|students?|campus|early[- ]career|working\s+student|werkstudent|"
    r"praktikum|alternance|summer\s+analyst)\b", re.I)
ENTRY = re.compile(r"\b(junior|jr|entry[- ]level|associate)\b", re.I)
BODY_EARLY = re.compile(
    r"\b(?:this|the)\s+(?:\w+\s+){0,2}(?:internship|co-?op|new[- ]grad(?:uate)?\s+(?:role|position|program)|"
    r"student\s+(?:role|position))\b", re.I)
EARLY_LEVELS = {"internship", "co-op", "new-grad", "entry"}


class Counts(dict):
    def __missing__(self, key):
        return 0


# ---------------------------------------------------------------------------- settings reading

def search_terms(settings: dict) -> list[str]:
    """Words a Workday or Phenom search can narrow by. Empty means the whole board: the user
    wants levels a word cannot pick out (mid, senior), or named none."""
    levels = set((settings.get("search") or {}).get("levels") or [])
    if not levels or not levels <= EARLY_LEVELS:
        return []
    out = []
    if "internship" in levels:
        out.append("intern")
    if "co-op" in levels:
        out += ["co-op", "coop"]
    if "new-grad" in levels:
        out += ["new grad", "graduate"]
    if "entry" in levels:
        out += ["junior", "entry level"]
    return out


def passes_level(title: str, description: str, settings: dict) -> bool:
    s = settings.get("search") or {}
    levels = set(s.get("levels") or [])
    if not levels or not levels <= EARLY_LEVELS:
        return True                              # the user wants levels we cannot tell from a title
    if EARLY.search(title) or ("entry" in levels and ENTRY.search(title)):
        return True
    low = title.lower()
    if any(k and k.lower() in low for k in s.get("include_keywords") or []):
        return True
    return bool(description and BODY_EARLY.search(description))


def too_old(posted_at: str, settings: dict) -> bool:
    days = (settings.get("search") or {}).get("max_posting_age_days")
    if not days or not posted_at:
        return False
    try:
        d = datetime.fromisoformat(posted_at)
    except ValueError:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d < datetime.now(timezone.utc) - timedelta(days=int(days))


def _wanted(settings: dict) -> list[str]:
    return [c.upper() for c in (settings.get("search") or {}).get("countries") or []]


def read_place(p: dict, settings: dict) -> dict:
    return locations.parse(p.get("location") or "", slug=p.get("slug") or "",
                           country_hint=p.get("country_hint") or "", workplace=p.get("workplace") or "",
                           prefer=_wanted(settings))


def in_country(place: dict, settings: dict) -> bool:
    """Keep a posting unless its location clearly names only countries the user did not pick."""
    wanted = set(_wanted(settings))
    return not wanted or not place["countries"] or bool(wanted & set(place["countries"]))


# -------------------------------------------------------------------------------- row building

def make_row(source: str, ident: str, p: dict, company: str, place: dict, now: str, extra_raw: dict) -> dict:
    desc = p.get("description") or ""
    return {
        "id": f"{source}:{ident}", "source": source, "company": company or "Unknown", "title": p["title"],
        "location": p.get("location") or "", "remote": 1 if place["remote"] else 0,
        "country": place["country"], "url": p["url"], "apply_url": p.get("apply_url") or p["url"],
        "ats": p.get("vendor") or (source if source in FETCHERS else ""), "description": desc,
        "posted_at": p.get("posted_at") or "", "first_seen_at": now, "deadline": p.get("deadline") or "",
        "fingerprint": dedupe.fingerprint_text(desc), "duplicate_of": "", "alive": 1,
        "raw": json.dumps({"job_id": p["job_id"], "countries": place["countries"],
                           "workplace": p.get("workplace") or "", **extra_raw}),
    }


_COLS = ["id", "source", "company", "title", "location", "remote", "country", "url", "apply_url", "ats",
         "description", "posted_at", "first_seen_at", "deadline", "fingerprint", "duplicate_of", "alive", "raw"]
_INSERT = f"INSERT OR IGNORE INTO postings ({', '.join(_COLS)}) VALUES ({', '.join('?' for _ in _COLS)})"


def _existing(con, ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ("SELECT id, alive, posted_at, length(description) > 0 AS has_desc FROM postings WHERE id IN (%s)"
             % ",".join("?" for _ in chunk))
        for r in con.execute(q, chunk):
            out[r["id"]] = dict(r)
    return out


# ------------------------------------------------------------------------------------ boards

def _read_board(board: dict, ctx: Ctx):
    try:
        return board, FETCHERS[board["ats"]](board, ctx), None
    except FetchError as e:
        return board, None, e
    except Exception as e:                          # a reader bug is one failed board, not a failed sweep
        return board, None, FetchError(f"{type(e).__name__}: {e}", "error")


def _handle_board(con, board, result, now, settings, rep, new_rows, body_queue):
    key = board_key(board)
    ats, token = board["ats"], str(board["token"]).lower()
    company = board.get("company") or token
    fetched = result.postings
    ids = [f"{ats}:{token}:{p['job_id']}" for p in fetched]
    have = _existing(con, ids)
    seen = set(ids)
    seen_rows = []
    queued: set[str] = set()
    for pid, p in zip(ids, fetched):
        if not p["title"] or not p["url"]:
            rep["unreadable_postings"] += 1
            continue
        if pid in queued:
            continue
        ex = have.get(pid)
        if ex:
            seen_rows.append((now, pid))
            if not ex["alive"]:
                con.execute("UPDATE postings SET alive=1 WHERE id=?", (pid,))
                rep["reopened"] += 1
            if not ex["has_desc"] and p.get("description"):
                con.execute("UPDATE postings SET description=?, fingerprint=? WHERE id=?",
                            (p["description"], dedupe.fingerprint_text(p["description"]), pid))
            elif not ex["has_desc"] and ats in BODY_FETCHERS:
                body_queue.append((board, p, pid, False))
            if not ex["posted_at"] and p.get("posted_at"):
                con.execute("UPDATE postings SET posted_at=? WHERE id=?", (p["posted_at"], pid))
            continue
        place = read_place(p, settings)
        if too_old(p.get("posted_at") or "", settings):
            rep["too_old"] += 1
            continue
        if not in_country(place, settings):
            rep["other_country"] += 1
            continue
        if not passes_level(p["title"], p.get("description") or "", settings):
            rep["other_level"] += 1
            continue
        row = make_row(ats, f"{token}:{p['job_id']}", p, company, place, now, {"board": token})
        queued.add(pid)
        new_rows.append((row, key))
        if not row["description"] and ats in BODY_FETCHERS:
            body_queue.append((board, p, row["id"], True))
    # postings the board no longer lists are closed, but only on a complete, believable read
    if result.complete:
        stored = {r[0] for r in con.execute("SELECT posting_id FROM posting_boards WHERE board_key=?", (key,))}
        gone = stored - seen
        if gone and not fetched and len(stored) >= EMPTY_ANSWER_GUARD:
            rep["empty_answers"] += 1               # a sudden empty list is more likely a fault than a clearing out
        else:
            for pid in gone:
                cur = con.execute("UPDATE postings SET alive=0 WHERE id=? AND alive=1", (pid,))
                rep["closed"] += cur.rowcount
    if seen_rows:
        con.executemany("UPDATE posting_boards SET last_seen_at=? WHERE posting_id=?", seen_rows)


def _record_state(con, board, now, status, count):
    key = board_key(board)
    con.execute(
        "INSERT INTO boards_state (board_key, ats, token, company, last_checked, last_status, last_count, failures)"
        " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(board_key) DO UPDATE SET last_checked=excluded.last_checked,"
        " last_status=excluded.last_status, last_count=excluded.last_count,"
        " failures=CASE WHEN excluded.last_status='ok' THEN 0 ELSE boards_state.failures + 1 END",
        (key, board["ats"], str(board["token"]), board.get("company") or "", now, status, count,
         0 if status == "ok" else 1))


def _fetch_bodies(queue, http, rep, run_id):
    """Posting text for rows whose board list had none. Failures are counted, never filled in."""
    queue = sorted(queue, key=lambda q: not q[3])[:MAX_BODIES]      # new postings first

    def one(item):
        board, p, pid, _new = item
        try:
            return item, BODY_FETCHERS[board["ats"]](board, p, http), None
        except FetchError as e:
            return item, None, e
        except Exception as e:
            return item, None, FetchError(f"{type(e).__name__}: {e}", "error")

    done = []
    with ThreadPoolExecutor(max_workers=min(WORKERS, 12)) as pool:
        for item, res, err in pool.map(one, queue):
            if err:
                rep["body_failed"] += 1
                store.log(run_id, f"No posting text for {item[2]}: {err}")
                continue
            done.append((item[2], res[0], res[1]))
    return done


# ------------------------------------------------------------------------------------ sweep

def sweep(run_id: str) -> str:
    settings = config.load_settings()
    src = settings.get("sources") or {}
    con = store.db()
    now = store.now()
    http = Http()
    rep = Counts()
    notes: list[str] = []
    new_rows: list[tuple[dict, str]] = []
    body_queue: list = []
    new_total = 0
    boards_checked = 0
    failed_kinds: dict[str, int] = {}

    if src.get("company_boards", True):
        if not boards_mod.discovered():
            # First sweep: grow the shipped seed list from the public directories so a new
            # user starts with thousands of boards, not only the seed.
            store.log(run_id, "First sweep: discovering company boards")
            try:
                notes.append(boards_mod.discover(run_id, http=http))
            except Exception as e:  # discovery failing never blocks the sweep
                notes.append(f"Board discovery did not finish ({e}); used the built-in list.")
        boards = boards_mod.load_all()
        ctx = Ctx(http=http, terms=search_terms(settings), countries=_wanted(settings))
        store.log(run_id, f"Reading {len(boards)} boards ({len(ctx.terms) or 'no'} search terms for Workday)")
        # Boards go through in batches and each batch's new postings are written straight away.
        # Holding every board's download until the end grew one sweep past 1.6 GB.
        n = 0
        batch_size = WORKERS * 4
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for start in range(0, len(boards), batch_size):
                futures = [pool.submit(_read_board, b, ctx) for b in boards[start:start + batch_size]]
                for fut in as_completed(futures):
                    board, result, err = fut.result()
                    n += 1
                    boards_checked += 1
                    if err:
                        failed_kinds[err.kind] = failed_kinds.get(err.kind, 0) + 1
                        _record_state(con, board, now, err.kind, 0)
                        store.log(run_id, f"Could not read {board['ats']}/{board['token']}: {err}")
                    else:
                        if result.note:
                            store.log(run_id, f"{board['ats']}/{board['token']}: {result.note}")
                        _handle_board(con, board, result, now, settings, rep, new_rows, body_queue)
                        _record_state(con, board, now, "ok", len(result.postings))
                        rep["listed"] += len(result.postings)
                    if n % 500 == 0:
                        store.log(run_id, f"{n} of {len(boards)} boards read, {new_total + len(new_rows)} new so far")
                del futures
                new_total += len(new_rows)
                _store_new(con, new_rows)
                new_rows.clear()
                con.commit()
    else:
        notes.append("Company boards are switched off in your settings.")

    # store the new board postings, then fetch the text the lists did not carry
    _store_new(con, new_rows)
    for pid, text, still_open in _fetch_bodies(body_queue, http, rep, run_id):
        if not still_open:
            con.execute("UPDATE postings SET alive=0 WHERE id=?", (pid,))
            rep["closed"] += 1
        elif text:
            con.execute("UPDATE postings SET description=?, fingerprint=? WHERE id=?",
                        (text, dedupe.fingerprint_text(text), pid))
            rep["bodies"] += 1
    con.commit()

    # sources read through the browser
    agg_new = 0
    for name in browser.enabled(settings):
        store.log(run_id, f"Reading {name} through your browser")
        rows, note = browser.collect(name, settings, run_id)
        if note:
            notes.append(f"{name}: {note}")
            store.log(run_id, f"{name}: {note}")
        agg_new += _store_aggregator(con, name, rows, now, settings, rep)
    con.commit()
    total_new = new_total + agg_new

    # postings that have no board to disappear from: look at the page
    _check_unboarded(con, http, now, rep)
    _mark_duplicates(con)
    con.commit()

    matches = _run_filters(run_id, now, notes)
    return _summary(boards_checked, total_new, matches, rep, failed_kinds, notes, src)


def _store_new(con, new_rows) -> None:
    con.executemany(_INSERT, [tuple(r[_c] for _c in _COLS) for r, _ in new_rows])
    con.executemany("INSERT OR REPLACE INTO posting_boards (posting_id, board_key, last_seen_at) VALUES (?,?,?)",
                    [(r["id"], key, r["first_seen_at"]) for r, key in new_rows])
    con.commit()


def _store_aggregator(con, name: str, rows: list[dict], now: str, settings: dict, rep: Counts) -> int:
    new = []
    ids = [f"{name}:{p['job_id']}" for p in rows]
    have = _existing(con, ids)
    for pid, p in zip(ids, rows):
        if pid in have:
            continue
        place = read_place(p, settings)
        if too_old(p.get("posted_at") or "", settings):
            rep["too_old"] += 1
            continue
        if not in_country(place, settings):
            rep["other_country"] += 1
            continue
        if not passes_level(p["title"], p.get("description") or "", settings):
            rep["other_level"] += 1
            continue
        new.append((make_row(name, p["job_id"], p, p["company"], place, now, {}), ""))
    con.executemany(_INSERT, [tuple(r[_c] for _c in _COLS) for r, _ in new])
    con.commit()
    return len(new)


def _check_unboarded(con, http: Http, now: str, rep: Counts) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECHECK_DAYS)).isoformat(timespec="seconds")
    boardless = [*browser.NAMES, "manual"]
    marks = ",".join("?" for _ in boardless)
    rows = con.execute(
        f"SELECT p.id, p.url FROM postings p LEFT JOIN liveness_checks c ON c.posting_id = p.id "
        f"WHERE p.alive=1 AND p.source IN ({marks}) AND p.first_seen_at < ? AND p.user_action = '' "
        f"AND (c.checked_at IS NULL OR c.checked_at < ?) ORDER BY c.checked_at IS NOT NULL, p.first_seen_at "
        f"LIMIT ?", (*boardless, now, cutoff, MAX_LIVENESS_CHECKS)).fetchall()
    for r in rows:
        result = liveness.check_url(http, r["url"])
        con.execute("INSERT OR REPLACE INTO liveness_checks (posting_id, checked_at, result) VALUES (?,?,?)",
                    (r["id"], now, result))
        if result == "dead":
            con.execute("UPDATE postings SET alive=0 WHERE id=?", (r["id"],))
            rep["closed"] += 1
        rep["page_checks"] += 1


def _mark_duplicates(con) -> None:
    since = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(timespec="seconds")
    rows = [dict(r) for r in con.execute(
        "SELECT id, source, company, title, country, url, first_seen_at, fingerprint, user_action, duplicate_of "
        "FROM postings WHERE alive=1 AND first_seen_at >= ?", (since,))]
    found = dedupe.find_duplicates([r for r in rows if not r["duplicate_of"]])
    con.executemany("UPDATE postings SET duplicate_of=? WHERE id=?", [(v, k) for k, v in found.items()])


def _run_filters(run_id: str, since: str, notes: list[str]):
    """Hand the new postings to the filters package. Returns the number that match, or None when
    the filters are not available."""
    try:
        from .. import filters
        evaluate_all = getattr(filters, "evaluate_all", None)
        if evaluate_all is None:
            raise ImportError("evaluate_all")
    except ImportError:
        notes.append("Postings were saved but not filtered yet.")
        return None
    try:
        evaluate_all(run_id)
    except Exception as e:                           # the postings are saved either way; say so
        store.log(run_id, f"Filtering failed: {e}")
        notes.append(f"Postings were saved but filtering failed: {e}")
        return None
    r = store.one("SELECT COUNT(*) AS n FROM postings WHERE first_seen_at >= ? AND verdict='keep' "
                  "AND duplicate_of='' AND alive=1", (since,))
    return r["n"] if r else 0


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def _summary(boards: int, new: int, matches, rep: Counts, failed: dict, notes: list[str], src: dict) -> str:
    s = f"Checked {_plural(boards, 'board')}, {_plural(new, 'new posting')}"
    s += f", {matches:,} match your settings." if matches is not None else "."
    bits = []
    nfail = sum(failed.values())
    if nfail:
        why = ", ".join(f"{n} {_KIND_WORDS.get(k, k)}" for k, n in sorted(failed.items(), key=lambda kv: -kv[1]))
        bits.append(f"{_plural(nfail, 'board')} could not be read ({why}).")
    if rep["closed"]:
        bits.append(f"{_plural(rep['closed'], 'posting')} closed.")
    if rep["reopened"]:
        bits.append(f"{_plural(rep['reopened'], 'posting')} reopened.")
    left = rep["other_country"] + rep["other_level"] + rep["too_old"]
    if left:
        bits.append(f"{left:,} others were outside your countries, levels or age limit.")
    if rep["body_failed"]:
        bits.append(f"Text for {_plural(rep['body_failed'], 'posting')} could not be fetched; they are saved without it.")
    if rep["empty_answers"]:
        bits.append(f"{_plural(rep['empty_answers'], 'board')} suddenly listed nothing and were left as they were.")
    bits.extend(notes)
    return " ".join([s, *bits])


_KIND_WORDS = {"http404": "gone", "unreachable": "unreachable", "rate-limited": "rate-limited",
               "bad-response": "unexpected answer", "error": "errors", "http403": "refused",
               "http500": "server errors", "http502": "server errors", "http503": "server errors"}


# ------------------------------------------------------------------------------- add by link

def add_manual(url: str, http: Http | None = None) -> dict:
    """Add one posting by its link. A link on a system we can read is fetched in full; any other
    link is stored with the page's own title. Returns the stored posting."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("That does not look like a web link.")
    http = http or Http()
    con = store.db()
    key = normalise_url(url)
    for r in con.execute("SELECT * FROM postings WHERE url=? OR apply_url=?", (url, url)):
        return dict(r)
    now = store.now()
    row = None
    parsed = detect.parse_job_url(url)
    if parsed:
        board, job_id = parsed
        posting = None
        try:
            posting = _fetch_one(board, job_id, url, http)
        except FetchError:
            posting = None
        if posting:
            token = str(board["token"]).lower()
            place = locations.parse(posting.get("location") or "", slug=posting.get("slug") or "",
                                    country_hint=posting.get("country_hint") or "",
                                    workplace=posting.get("workplace") or "")
            row = make_row(board["ats"], f"{token}:{posting['job_id']}", posting, board.get("company") or token,
                           place, now, {"board": token, "added": "link"})
    if row is None:
        title, company = _page_title(url, http)
        ident = hashlib.sha1(key.encode()).hexdigest()[:16]
        place = locations.parse("")
        p = {"job_id": ident, "title": title, "url": url, "apply_url": url, "vendor": detect.vendor_of(url)}
        row = make_row("manual", ident, p, company, place, now, {"added": "link"})
    con.execute(_INSERT, tuple(row[c] for c in _COLS))
    con.commit()
    return dict(con.execute("SELECT * FROM postings WHERE id=?", (row["id"],)).fetchone())


def _fetch_one(board: dict, job_id: str, url: str, http: Http) -> dict | None:
    if board["ats"] == "workday":
        return workday.fetch_one(board, job_id if job_id.startswith("/") else _wd_path(url), http)
    fetch = FETCHERS.get(board["ats"])
    if not fetch:
        return None
    res = fetch(board, Ctx(http=http))
    want = normalise_url(url)
    for p in res.postings:
        if p["job_id"] == job_id or normalise_url(p["url"]) == want:
            if not p.get("description") and board["ats"] in BODY_FETCHERS:
                try:
                    p["description"], _ = BODY_FETCHERS[board["ats"]](board, p, http)
                except FetchError:
                    pass
            return p
    return None


def _wd_path(url: str) -> str:
    parsed = workday.parse_url(url)
    return parsed[1] if parsed else ""


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_OG_SITE = re.compile(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', re.I)


def _page_title(url: str, http: Http) -> tuple[str, str]:
    """(title, company) from the page itself. The company is the site's own name when it gives
    one, else its host; the title falls back to the link."""
    import urllib.parse
    host = (urllib.parse.urlparse(url).hostname or "").removeprefix("www.")
    try:
        _, html_text = http.final_url(url)
    except FetchError:
        return url, host or "Unknown"
    m = _TITLE_RE.search(html_text)
    title = strip_html(m.group(1)).strip() if m else ""
    site = _OG_SITE.search(html_text)
    company = strip_html(site.group(1)).strip() if site else host
    return title or url, company or host or "Unknown"
