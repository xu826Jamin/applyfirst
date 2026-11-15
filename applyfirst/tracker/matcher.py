"""Place an email on one of the user's applications, or say plainly that it cannot be placed.

Ported from the working outcome sweep. Evidence order: a requisition id, then the employer
(named in the subject or sender, an alias, or a sender domain learned earlier), then the role
words. Anything ambiguous is returned as unmatched with its candidates; it is never guessed.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from .. import config
from . import classifier as C

LEGAL = {"inc", "incorporated", "ltd", "limited", "llc", "lp", "corp", "corporation", "co",
         "company", "canada", "gmbh", "plc", "sa", "se", "ag", "group", "holdings", "the", "and"}
GENERIC_FIRST = {"general", "new", "north", "south", "global", "first", "royal", "bank",
                 "united", "american", "canadian", "national", "digital", "advanced",
                 "applied", "blue", "green", "smart", "open", "great", "human", "red"}
ROLE_STOP = {"intern", "internship", "internships", "co", "op", "coop", "student", "winter",
             "summer", "fall", "spring", "january", "may", "months", "month", "the", "and", "of",
             "in", "for", "with", "a", "an", "to", "program", "role", "position", "toronto",
             "ontario", "on", "at", "or", "full", "time", "term", "start", "from", "new", "grad",
             "canada", "remote", "hybrid", "list", "board"}
COMMON_WORD_KEYS = {"later", "super", "zip", "ramp", "open", "scale", "stack", "bright"}
COUNTER_RE = re.compile(r"\((?:confirmation|duplicate|copy|attempt|resubmi\w*)\b[^)]*\)", re.I)
# Statuses an email can legitimately be about.
LIVE_STATUSES = ("filling", "ready-to-submit", "submitted")


# --------------------------------------------------------------------------- aliases

def load_aliases() -> tuple[dict[str, list[re.Pattern]], dict[str, list[int]]]:
    """(employer key -> patterns, requisition id -> application ids): shipped list plus the
    user's own <data home>/tracker_aliases.json."""
    companies: dict[str, list[str]] = {}
    ids: dict[str, list[int]] = {}
    sources = [Path(__file__).parent / "aliases.json", config.path("tracker_aliases.json")]
    for p in sources:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k, v in (data.get("companies") or {}).items():
            companies.setdefault(k.lower(), []).extend(str(x) for x in v)
        for k, v in (data.get("ids") or {}).items():
            ids[k.lower()] = [int(x) for x in v]
    pats = {k: [re.compile(re.escape(x.lower())) for x in v] for k, v in companies.items()}
    return pats, ids


# --------------------------------------------------------------------------- text helpers

def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower().replace("&", " and "))


def employer_key(company: str) -> str:
    base = re.sub(r"\([^)]*\)", " ", company or "")
    toks = [t for t in words(base) if t not in LEGAL]
    if not toks:
        return ""
    if (toks[0] in GENERIC_FIRST or len(toks[0]) < 3) and len(toks) > 1:
        return " ".join(toks[:2])
    return toks[0]


def company_extra_tokens(company: str, key: str) -> set[str]:
    inner = " ".join(re.findall(r"\(([^)]*)\)", company or ""))
    return {t for t in words(inner) if t not in LEGAL and t not in key.split()
            and t not in ROLE_STOP and not t.isdigit()}


def role_tokens(role: str) -> set[str]:
    base = re.sub(r"\([^)]*\)", " ", role or "")
    return {t for t in words(base) if t not in ROLE_STOP and not t.isdigit() and len(t) > 1}


def role_title(role: str) -> str:
    """The posting title: up to the first comma outside parentheses, counters dropped."""
    role = COUNTER_RE.sub(" ", role or "")
    depth, cut = 0, len(role)
    for i, ch in enumerate(role):
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth <= 0:
            cut = i
            break
    return " ".join(words(role[:cut]))


def dup_identity(app: dict) -> tuple:
    """What makes two applications the SAME one: company, title (a parenthetical or a
    different posting makes a different application) and posting."""
    role = COUNTER_RE.sub(" ", app["title"] or "")
    return (app["company"].lower(), " ".join(words(role)), app.get("posting_id") or "")


def msg_tokens(msg: dict) -> set[str]:
    return set(words(msg.get("subject", "") + " " + msg.get("body", "")))


def find_ids(msg: dict) -> set[str]:
    text = (msg.get("subject", "") + " " + msg.get("body", "")).lower()
    return set(re.findall(r"\b(?:[a-z]{1,3})?\d{5,}[a-z0-9-]*\b", text))


def _day(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- the pool

def load_pool() -> list[dict]:
    """Applications an email can be about, with the evidence text used to match them."""
    from .. import store
    marks = ",".join("?" for _ in LIVE_STATUSES)
    apps = store.rows(
        f"SELECT a.id, a.posting_id, a.company, a.title, a.status, a.submitted_at, a.created_at, "
        f"a.outcome, a.notes, p.url, p.apply_url FROM applications a "
        f"LEFT JOIN postings p ON p.id = a.posting_id WHERE a.status IN ({marks})",
        LIVE_STATUSES)
    for a in apps:
        a["key"] = employer_key(a["company"])
        a["ref_date"] = (a["submitted_at"] or a["created_at"] or "")[:10]
        a["idtext"] = " ".join(str(a.get(k) or "") for k in
                               ("company", "title", "posting_id", "url", "apply_url", "notes")).lower()
    return apps


class Pool:
    def __init__(self, apps: list[dict], learned: dict[str, str] | None = None):
        self.apps = {a["id"]: a for a in apps}
        self.by_key: dict[str, list[int]] = {}
        for a in apps:
            if a["key"]:
                self.by_key.setdefault(a["key"], []).append(a["id"])
        self.learned = dict(learned or {})
        self.alias_patterns, self.alias_ids = load_aliases()


# --------------------------------------------------------------------------- employer

def employer_scores(msg: dict, pool: Pool) -> dict[str, int]:
    """employer key -> evidence score. Subject or sender evidence is worth 3, body 1."""
    subj = msg.get("subject", "").lower()
    frm = (msg.get("from") or "").lower()
    body_low = msg.get("body", "").lower()
    dom = C.sender_domain(frm)
    scores: dict[str, int] = {}
    sender_tokens = [t for t in re.split(r"[^a-z0-9]+", frm) if len(t) >= 4]
    for key in pool.by_key:
        if len(key) < 3:
            continue
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])")
        s = 0
        if pat.search(subj):
            s += 3
        flat = key.replace(" ", "")
        if len(flat) >= 4 and any(t == flat or t.startswith(flat) for t in sender_tokens):
            s += 3
        if pool.learned.get(dom) == key:
            s += 3
        if key not in COMMON_WORD_KEYS and pat.search(body_low):
            s += 1
        for al in pool.alias_patterns.get(key, []):
            if al.search(subj) or al.search(frm) or al.search(body_low):
                s += 3
                break
        if s:
            scores[key] = s
    return scores


def pick_employer(scores: dict[str, int]) -> tuple[str | None, str]:
    if not scores:
        return None, "no employer named in the email"
    top = max(scores.values())
    best = [k for k, v in scores.items() if v == top]
    if len(best) > 1:
        return None, "several employers fit equally: " + ", ".join(sorted(best))
    return best[0], ""


def is_trusted(msg: dict, pool: Pool, scores: dict[str, int] | None = None) -> bool:
    """Application mail: a known ATS sender, a sender domain learned for an employer, or an
    employer clearly named plus application wording. Anything else is not read as a reply."""
    frm = msg.get("from", "")
    if C.is_newsletter(frm):
        return False
    scores = employer_scores(msg, pool) if scores is None else scores
    text = msg.get("subject", "") + " " + msg.get("body", "")
    evidence = bool(C.APP_EVIDENCE_RE.search(text))
    return (C.is_ats(frm) or pool.learned.get(C.sender_domain(frm)) is not None
            or (bool(scores) and max(scores.values()) >= 3 and evidence))


# --------------------------------------------------------------------------- the match

def _result(ids: list[int], reason: str, employer: str | None, ambiguous: bool = False,
            candidates: list[int] | None = None) -> dict:
    return {"app_ids": ids, "reason": reason, "employer": employer, "ambiguous": ambiguous,
            "candidates": candidates if candidates is not None else list(ids)}


def exact_title_apps(cand: list[int], pool: Pool, msg: dict) -> list[int]:
    text = " " + " ".join(words(msg.get("subject", "") + " " + msg.get("body", ""))) + " "
    hits = []
    for n in cand:
        t = role_title(pool.apps[n]["title"])
        if len(t.split()) >= 2 and f" {t} " in text:
            hits.append((len(t.split()), n))
    if not hits:
        return []
    top = max(h[0] for h in hits)
    ids = [n for k, n in hits if k == top]
    if len({dup_identity(pool.apps[n]) for n in ids}) != 1:
        return []
    return ids


def match(msg: dict, cls: str, pool: Pool) -> dict:
    """-> {app_ids, reason, employer, ambiguous, candidates}. app_ids is empty when unplaced.

    Identical duplicate applications (same company, title and posting) resolve to the first
    one, so a reply is never counted twice.
    """
    day = _day(msg.get("date", ""))
    ids = find_ids(msg)
    for i in sorted(ids):
        hit = [a for a in pool.alias_ids.get(i, []) if a in pool.apps]
        if hit:
            return _result(hit[:1], f"requisition id {i} (your aliases file)",
                           pool.apps[hit[0]]["key"], candidates=hit)
    key, why = pick_employer(employer_scores(msg, pool))
    if key is None:
        return _result([], why, None, candidates=[])
    cand = []
    for n in pool.by_key[key]:
        ref = _day(pool.apps[n]["ref_date"])
        # a reply dated before the application cannot be about it (one day of slack for time zones)
        if day is None or ref is None or day >= ref - timedelta(days=1):
            cand.append(n)
    if not cand:
        return _result([], f"{key}: every application is dated after this email", key,
                       candidates=[])
    for i in sorted(ids):
        by_id = [n for n in cand if i in pool.apps[n]["idtext"]]
        if by_id:
            return _dedupe(by_id, pool, key, f"id {i} appears in the application")
    if len(cand) == 1:
        return _result(cand, f"{key}: the only application to this employer", key)
    exact = exact_title_apps(cand, pool, msg)
    if exact:
        return _dedupe(exact, pool, key, "the email names this exact title")
    toks = msg_tokens(msg)
    scored = []
    for n in cand:
        a = pool.apps[n]
        rt = role_tokens(a["title"])
        ov = len(rt & toks)
        cov = ov / len(rt) if rt else 0.0
        extra = len(company_extra_tokens(a["company"], key) & toks)
        scored.append((ov, extra, cov, n))
    best_ov = max(s[0] for s in scored)
    pool_ = [s for s in scored if s[0] == best_ov]
    best_extra = max(s[1] for s in pool_)
    pool_ = [s for s in pool_ if s[1] == best_extra]
    best_cov = max(s[2] for s in pool_)
    pool_ = [s for s in pool_ if s[2] == best_cov]
    tied = [s[3] for s in pool_]
    if best_ov == 0 or not (best_cov >= 0.5 or best_ov >= 2):
        return _result([], f"{key}: {len(cand)} applications and the email shares no role words",
                       key, ambiguous=True, candidates=cand[:12])
    if len(tied) == 1:
        return _result(tied, f"{key}: role words match ({best_ov})", key)
    return _dedupe(tied, pool, key, "role words match", ambiguous_candidates=tied)


def _dedupe(ids: list[int], pool: Pool, key: str, why: str,
            ambiguous_candidates: list[int] | None = None) -> dict:
    same = {dup_identity(pool.apps[n]) for n in ids}
    if len(ids) == 1:
        return _result(ids, f"{key}: {why}", key)
    if len(same) == 1:
        first = min(ids)
        return _result([first], f"{key}: {why}; {len(ids)} identical applications, used the first",
                       key, candidates=sorted(ids))
    return _result([], f"{key}: {len(ids)} applications fit equally", key, ambiguous=True,
                   candidates=sorted(ids))


# --------------------------------------------------------------------------- batch analysis

def analyze_once(msgs: list[dict], pool: Pool) -> list[dict]:
    results = []
    for m in msgs:
        res = {"msg": m, "class": "other", "trusted": False, "app_ids": [], "reason": "",
               "ambiguous": False, "candidates": [], "employer": None}
        frm = m.get("from", "")
        if C.is_newsletter(frm):
            res["reason"] = "newsletter or job-alert sender"
            results.append(res)
            continue
        scores = employer_scores(m, pool)
        if not is_trusted(m, pool, scores):
            res["reason"] = "not application mail: no applicant system and no employer named"
            results.append(res)
            continue
        res["trusted"] = True
        cls = C.classify(m.get("subject", ""), m.get("body", ""), frm)
        res["class"] = cls
        mt = match(m, cls, pool)
        res.update(app_ids=mt["app_ids"], reason=mt["reason"], ambiguous=mt["ambiguous"],
                   candidates=mt["candidates"], employer=mt["employer"])
        results.append(res)
    # an unplaced message takes the unique placement of its own thread
    by_thread: dict[str, set[tuple]] = {}
    for r in results:
        t = r["msg"].get("thread_id")
        if r["app_ids"] and t:
            by_thread.setdefault(t, set()).add(tuple(r["app_ids"]))
    for r in results:
        t = r["msg"].get("thread_id")
        if r["trusted"] and not r["app_ids"] and t in by_thread and len(by_thread[t]) == 1:
            r["app_ids"] = list(next(iter(by_thread[t])))
            r["reason"] = "same conversation as an email already placed"
            r["ambiguous"] = False
    return results


def learnable_domains(results: list[dict], already: dict[str, str]) -> dict[str, str]:
    """Sender domains of placed, non-ATS, non-free-mail messages: domain -> employer key."""
    new: dict[str, str] = {}
    for r in results:
        frm = r["msg"].get("from", "")
        dom = C.sender_domain(frm)
        if r["app_ids"] and r["employer"] and dom and not C.is_ats(frm) \
                and dom not in C.FREE_MAIL and dom not in already:
            new[dom] = r["employer"]
    return new


def analyze(msgs: list[dict], pool: Pool) -> tuple[list[dict], dict[str, str]]:
    """Two passes: the first places what it can and learns each employer's own sender
    domain; the second re-reads everything with those domains known, so an anonymous
    'Thank you for applying' from a domain first seen on a named email is placed too.
    Returns (results, newly learned domains)."""
    first = analyze_once(msgs, pool)
    new = learnable_domains(first, pool.learned)
    if not new:
        return first, {}
    pool.learned.update(new)
    return analyze_once(msgs, pool), new
