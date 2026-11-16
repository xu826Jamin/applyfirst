"""apply: fill and submit applications by running Claude Code headless with a browser.

See docs/CONTRACTS.md. In short:

    apply_queue(run_id, limit)   run the queue: approved postings (and, in auto mode once the
                                 first `apply.review_first` have been reviewed, kept ones)
    standard_answers(...)        the answers derived from the profile
    learn(question, answer)      store an answer for reuse
    workday_fill.js              the one-call Workday filler the brief points Claude at
"""
from __future__ import annotations

import importlib
import os
from typing import Any, Iterator

from .. import claude, config, store
from .answers import (  # noqa: F401  (public API)
    learn, learned_answers, mark_pending, normalize_key, pending_for, questions_of,
    record_used, salary_from_posting, standard_answers, workday_answers,
)
from .brief import RESULT_SCHEMA, STATUSES, build_brief, is_workday
from . import email_code, lessons

# Statuses that mean "this posting is taken care of": never apply to it again.
DONE_STATUSES = ("submitted", "ready-to-submit", "filling")
MAX_AUTO_RETRIES = 3
REVIEWED = ("ready-to-submit", "submitted")


# --------------------------------------------------------------------------- other packages


def _need(module: str, attr: str, why: str):
    """Import a function from a sibling package lazily, with a plain message when it is absent."""
    try:
        fn = getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError) as e:
        raise RuntimeError(
            f"Applying needs {module}.{attr} ({why}), which is not available yet: {e}. "
            "Update applyfirst or finish setting up that part, then run again.") from e
    return fn


# --------------------------------------------------------------------------- queue bookkeeping


def _today() -> str:
    return store.now()[:10]


def _started_today() -> int:
    row = store.one(
        "SELECT COUNT(DISTINCT a.id) n FROM applications a "
        "LEFT JOIN application_costs c ON c.application_id=a.id "
        "WHERE substr(a.created_at,1,10)=? OR substr(c.created_at,1,10)=?", (_today(), _today()))
    return row["n"] if row else 0


def _reviewed_count() -> int:
    marks = ",".join("?" for _ in REVIEWED)
    row = store.one(
        f"SELECT COUNT(DISTINCT application_id) n FROM application_costs "
        f"WHERE mode='review' AND outcome_status IN ({marks})", REVIEWED)
    return row["n"] if row else 0


def _mode_for_next(settings: dict) -> str:
    """review | auto for the next application. Auto mode still reviews the first N."""
    if config.get(settings, "apply.mode", "review") != "auto":
        return "review"
    first = int(config.get(settings, "apply.review_first", 0) or 0)
    return "review" if _reviewed_count() < first else "auto"


def _norm(text: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in (text or "").lower()).split())


def _skip_reason(posting: dict) -> str | None:
    """Why a posting must not be applied to now, or None. Existing queued rows are handled apart."""
    if posting.get("alive") == 0:
        return "posting is closed"
    row = store.one("SELECT id FROM applications WHERE posting_id=? AND status IN (?,?,?) LIMIT 1",
                    (posting["id"], *DONE_STATUSES))
    if row:
        return "already applied"
    other = store.one("SELECT id, status, posting_id FROM applications WHERE posting_id=? ORDER BY id DESC LIMIT 1",
                      (posting["id"],))
    if other and other["status"] != "queued":
        return f"already tried ({other['status']})"
    # The same role listed on two boards: skip when its twin already went out.
    twin = store.one(
        "SELECT id FROM applications WHERE status IN (?,?,?) AND lower(company)=lower(?) AND lower(title)=lower(?)",
        (*DONE_STATUSES, posting.get("company", ""), posting.get("title", "")))
    if twin:
        return "same role already applied to"
    return None


def _retry_ready() -> list[dict]:
    """Applications that stopped on questions, which have all been answered since."""
    out = []
    for app in store.rows("SELECT * FROM applications WHERE status='needs-you' ORDER BY id"):
        qs = questions_of(app["id"])
        if not qs or pending_for(app["id"]):
            continue
        tries = (store.one("SELECT COUNT(*) n FROM application_costs WHERE application_id=?", (app["id"],)) or {}).get("n", 0)
        if tries >= MAX_AUTO_RETRIES:
            continue
        out.append(app)
    return out


def _candidates(settings: dict, queue_fn) -> Iterator[tuple[dict, int | None]]:
    """Postings to apply to, in order, each with an existing application id when re-running one."""
    seen: set[str] = set()

    def posting_row(pid: str) -> dict | None:
        return store.one("SELECT * FROM postings WHERE id=?", (pid,))

    # 1. Rows already queued (or re-queued by the user), then answered needs-you rows.
    for app in store.rows("SELECT * FROM applications WHERE status='queued' ORDER BY id") + _retry_ready():
        p = posting_row(app["posting_id"] or "")
        if p and p["id"] not in seen:
            seen.add(p["id"])
            yield p, app["id"]
    # 2. Approved postings.
    for p in queue_fn(settings, "approved", limit=500):
        if p["id"] not in seen and not _skip_reason(p):
            seen.add(p["id"])
            yield p, None
    # 3. Kept postings: auto mode only, once the first few have been reviewed.
    if config.get(settings, "apply.mode", "review") == "auto":
        if _reviewed_count() >= int(config.get(settings, "apply.review_first", 0) or 0):
            for p in queue_fn(settings, "kept", limit=500):
                if p["id"] not in seen and not _skip_reason(p):
                    seen.add(p["id"])
                    yield p, None


# --------------------------------------------------------------------------- one application


def _set(app_id: int, **fields: Any) -> None:
    fields["updated_at"] = store.now()
    cols = ", ".join(f"{k}=?" for k in fields)
    store.execute(f"UPDATE applications SET {cols} WHERE id=?", (*fields.values(), app_id))


def _confirmed_experience(limit: int = 80) -> list[str]:
    rows = store.rows(
        "SELECT section, title, org, dates, text FROM experience WHERE confirmed=1 "
        "ORDER BY position LIMIT ?", (limit,))
    lines = []
    for r in rows:
        if r.get("text"):
            lines.append(r["text"])
        else:
            head = " at ".join(x for x in (r.get("title"), r.get("org")) if x)
            lines.append(f"{head} ({r['dates']})" if r.get("dates") else head)
    return [l for l in lines if l]


def _cover_letter(posting: dict, settings: dict) -> str | None:
    setting = config.get(settings, "apply.cover_letters", "when-required")
    if setting == "never":
        return None
    text = (posting.get("description") or "").lower()
    if setting == "always" or "cover letter" in text:
        fn = _need("applyfirst.resume", "cover_letter", "builds the cover letter")
        path = fn(posting)
        return path if path and os.path.exists(path) else None
    return None


def _record_cost(app_id: int, run_id: str, mode: str, res: claude.Result, status: str) -> None:
    store.execute(
        "INSERT INTO application_costs (application_id, run_id, mode, cost_usd, turns, outcome_status, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (app_id, run_id, mode, float(res.cost_usd or 0.0), int(res.turns or 0), status, store.now()))


def _forbidden_in_notes(posting: dict, profile: dict) -> list[str]:
    """Words a form note may not contain: the company and the person's own details."""
    name = profile.get("name") or {}
    loc = profile.get("location") or {}
    return [posting.get("company", ""), name.get("first", ""), name.get("last", ""),
            name.get("preferred", ""), profile.get("email", ""), profile.get("phone", ""),
            loc.get("city", ""), loc.get("postal_code", "")]


def _finish(app_id: int, res: claude.Result, mode: str, standard: dict,
            posting: dict | None = None, profile: dict | None = None) -> tuple[str, str]:
    """Turn Claude's report into the application's final row. Returns (status, reason)."""
    data = res.structured if isinstance(res.structured, dict) else None
    if not data or data.get("status") not in STATUSES:
        why = res.error or "Claude did not return a result for this application."
        _set(app_id, status="failed", needs_you="", notes=why[:2000])
        return "failed", why

    status = data["status"]
    reason = (data.get("needs_you_reason") or "").strip()
    notes = (data.get("notes") or "").strip()
    confirmation = (data.get("confirmation_text") or "").strip()

    # A file field is not a question the person can answer on the Answers screen: the resume or
    # cover letter is attached by applyfirst, so a failed upload stays in the reason instead.
    asked = [q for q in data.get("pending_questions") or []
             if isinstance(q, dict) and q.get("question") and (q.get("type") or "").lower() != "file"]
    for q in asked:
        mark_pending(app_id, q["question"], q.get("type", ""), q.get("options") or [])
    questions = bool(asked)
    if questions and status != "submitted":
        status = "needs-you"
        reason = reason or "A required question needs your answer."
    if status == "submitted" and not confirmation:
        # Submitting is spent once: say what is known instead of claiming success.
        status = "needs-you"
        reason = "Submit was clicked but no confirmation was shown. Check the page or your email."
    if status == "needs-you" and not reason:
        reason = "Needs your attention."
    if status == "ready-to-submit":
        reason = ""

    record_used(data.get("answers_used") or [], standard)
    if posting is not None:
        lessons.record(lessons.form_system(posting), data.get("form_lessons") or [],
                       _forbidden_in_notes(posting, profile or {}))

    fields: dict[str, Any] = {"status": status, "needs_you": reason if status == "needs-you" else "",
                              "notes": "\n".join(x for x in (f"Confirmation: {confirmation}" if confirmation else "", notes) if x)[:4000]}
    if status == "submitted":
        fields["submitted_at"] = store.now()
    _set(app_id, **fields)
    return status, reason


def _apply_one(posting: dict, existing_id: int | None, run_id: str, settings: dict, profile: dict) -> tuple[str, int]:
    """Run one application end to end. Returns (final status, app id)."""
    mode = _mode_for_next(settings)
    app_id = existing_id
    if app_id is None:
        app_id = store.execute(
            "INSERT INTO applications (posting_id, company, title, status, run_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (posting["id"], posting.get("company", ""), posting.get("title", ""), "queued", run_id, store.now(), store.now()))
    _set(app_id, status="filling", needs_you="", run_id=run_id)

    try:
        resume_for = _need("applyfirst.resume", "resume_for", "picks the resume file")
        resume_path = resume_for(posting, settings)
        if not resume_path or not os.path.exists(resume_path):
            raise RuntimeError("No resume file could be prepared. Import your resume and confirm your experience first.")
        cover = _cover_letter(posting, settings)
        _set(app_id, resume_file=os.path.basename(resume_path), cover_letter_file=os.path.basename(cover) if cover else "")

        standard = standard_answers(profile, settings, posting)
        workday = workday_answers(standard, posting) if is_workday(posting) else None
        browser = config.get(settings, "apply.browser", "chrome-extension")
        code_tool = mode == "auto" and browser == "chrome-extension" and email_code.is_available()
        brief = build_brief(
            posting, mode=mode, resume_path=resume_path, cover_letter_path=cover,
            cover_letters_setting=config.get(settings, "apply.cover_letters", "when-required"),
            standard=standard, learned=learned_answers(), experience=_confirmed_experience(),
            settings_apply=settings.get("apply", {}), browser=config.get(settings, "apply.browser", "chrome-extension"),
            workday=workday,
            form_notes=lessons.brief_section(lessons.form_system(posting)),
            email_code_tool=code_tool,
        )
    except Exception as e:  # recorded on the row, never swallowed
        _set(app_id, status="failed", notes=str(e)[:2000])
        store.log(run_id, f"{posting.get('company')} / {posting.get('title')}: failed before filling: {e}")
        return "failed", app_id

    res = claude.run(
        brief, run_id,
        browser=config.get(settings, "apply.browser", "chrome-extension"),
        json_schema=RESULT_SCHEMA,
        max_turns=config.get(settings, "claude.max_turns_per_application", 60),
        upload_files=[resume_path] + ([cover] if cover else []),
        mcp_servers={"applyfirst": email_code.server_config(posting.get("company", ""))} if code_tool else None,
    )
    status, reason = _finish(app_id, res, mode, standard, posting, profile)
    _record_cost(app_id, run_id, mode, res, status)
    store.log(run_id, f"{posting.get('company')} / {posting.get('title')}: {status}"
                      + (f" ({reason})" if reason else "") + f", cost ${res.cost_usd:.2f}")
    return status, app_id


# --------------------------------------------------------------------------- the queue


def apply_queue(run_id: str, limit: int | None = None) -> str:
    settings = config.load_settings()
    profile = config.load_profile()
    queue_fn = _need("applyfirst.filters", "queue", "lists the postings you approved")
    _need("applyfirst.resume", "resume_for", "picks the resume file")

    daily = int(config.get(settings, "queue.daily_limit", 25) or 0)
    budget = max(0, daily - _started_today())
    if limit is not None:
        budget = min(budget, limit)
    if budget <= 0:
        return f"Nothing to do: today's limit of {daily} applications is already used."

    counts = {"submitted": 0, "ready-to-submit": 0, "needs-you": 0, "failed": 0}
    cost_before = (store.one("SELECT COALESCE(SUM(cost_usd),0) c FROM application_costs") or {}).get("c", 0.0)
    done = 0
    fail_streak = 0
    warnings: list[str] = []
    for posting, existing in _candidates(settings, queue_fn):
        if done >= budget:
            break
        status, _ = _apply_one(posting, existing, run_id, settings, profile)
        counts[status] = counts.get(status, 0) + 1
        done += 1
        fail_streak = fail_streak + 1 if status == "failed" else 0
        if status == "failed":
            warn = lessons.recurring_failure(lessons.form_system(posting))
            if warn and warn not in warnings:
                store.log(run_id, warn)
                warnings.append(warn)
        if fail_streak >= 3:
            store.log(run_id, "Stopping: three applications in a row failed.")
            break

    cost = (store.one("SELECT COALESCE(SUM(cost_usd),0) c FROM application_costs") or {}).get("c", 0.0) - cost_before
    if not done:
        return "No approved postings to apply to. Approve some on the Jobs screen first."
    bits = []
    if counts["submitted"]:
        bits.append(f"submitted {counts['submitted']}")
    if counts["ready-to-submit"]:
        bits.append(f"{counts['ready-to-submit']} ready for you to review and submit")
    if counts["needs-you"]:
        bits.append(f"{counts['needs-you']} need you")
    if counts["failed"]:
        bits.append(f"{counts['failed']} failed")
    return (f"Worked on {done} applications: " + ", ".join(bits) + f". Cost ${cost:.2f}."
            + "".join(" " + w for w in warnings))
