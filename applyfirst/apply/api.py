"""Routes for the apply package, mounted at /api/apply."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from .. import jobs, store
from . import apply_queue, lessons, normalize_key, questions_of

router = APIRouter()

STATUS_CHOICES = ("queued", "filling", "needs-you", "ready-to-submit", "submitted", "failed")


@router.post("/run")
def run(body: dict | None = None) -> dict:
    limit = (body or {}).get("limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise HTTPException(422, "limit must be a whole number.")
    try:
        run_id = jobs.spawn("apply", lambda rid: apply_queue(rid, limit))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"run_id": run_id}


@router.get("/applications")
def applications(status: str = "") -> list[dict]:
    wanted = [s.strip() for s in status.split(",") if s.strip()]
    sql = (
        "SELECT a.*, COALESCE((SELECT SUM(cost_usd) FROM application_costs c WHERE c.application_id=a.id), 0) AS cost_usd, "
        "p.url AS posting_url, p.apply_url AS apply_url "
        "FROM applications a LEFT JOIN postings p ON p.id=a.posting_id"
    )
    params: list = []
    if wanted:
        sql += " WHERE a.status IN (" + ",".join("?" for _ in wanted) + ")"
        params = wanted
    rows = store.rows(sql + " ORDER BY a.updated_at DESC, a.id DESC", params)
    for r in rows:
        r["questions"] = [{**q, "options": json.loads(q["options"] or "[]")} for q in questions_of(r["id"])]
    return rows


@router.post("/applications/{app_id}/status")
def set_status(app_id: int, body: dict) -> dict:
    status = body.get("status")
    if status not in STATUS_CHOICES:
        raise HTTPException(422, "status must be one of: " + ", ".join(STATUS_CHOICES))
    if not store.one("SELECT id FROM applications WHERE id=?", (app_id,)):
        raise HTTPException(404, "No such application.")
    fields = ["status=?", "updated_at=?"]
    params: list = [status, store.now()]
    if status == "submitted":
        fields.append("submitted_at=?")
        params.append(store.now())
    if status != "needs-you":
        fields.append("needs_you=''")
    store.execute(f"UPDATE applications SET {', '.join(fields)} WHERE id=?", (*params, app_id))
    return store.one("SELECT * FROM applications WHERE id=?", (app_id,)) or {}


@router.get("/answers")
def answers(pending: int | None = None) -> list[dict]:
    sql, params = "SELECT * FROM answers", []
    if pending is not None:
        sql += " WHERE pending=?"
        params.append(1 if pending else 0)
    rows = store.rows(sql + " ORDER BY pending DESC, uses DESC, updated_at DESC", params)
    for r in rows:
        qs = store.rows("SELECT application_id, type, options FROM application_questions WHERE key=?", (r["key"],))
        r["type"] = next((q["type"] for q in qs if q["type"]), "")
        r["options"] = next((json.loads(q["options"]) for q in qs if q["options"] not in ("", "[]")), [])
        r["application_ids"] = [q["application_id"] for q in qs]
    return rows


@router.put("/answers/{key:path}")
def put_answer(key: str, body: dict) -> dict:
    answer = str(body.get("answer", "")).strip()
    if not answer:
        raise HTTPException(422, "The answer cannot be empty.")
    k = normalize_key(key) or key
    row = store.one("SELECT key FROM answers WHERE key=?", (k,))
    now = store.now()
    if row:
        store.execute("UPDATE answers SET answer=?, source='user', pending=0, updated_at=? WHERE key=?", (answer, now, k))
    else:
        store.upsert("answers", {"key": k, "question": key, "answer": answer, "source": "user",
                                 "pending": 0, "updated_at": now}, key="key")
    return store.one("SELECT * FROM answers WHERE key=?", (k,)) or {}


@router.get("/form-notes")
def form_notes() -> list[dict]:
    """Per form system: how applications ended, and what earlier applications learned."""
    return lessons.overview()


@router.delete("/form-notes/{system}/{key:path}")
def delete_form_note(system: str, key: str) -> dict:
    if not lessons.delete(system, key):
        raise HTTPException(404, "No such note.")
    return {"deleted": key}


@router.get("/cost")
def cost() -> dict:
    t = store.one(
        "SELECT COUNT(DISTINCT application_id) apps, COUNT(*) runs, COALESCE(SUM(cost_usd),0) total FROM application_costs"
    ) or {"apps": 0, "runs": 0, "total": 0}
    apps = t["apps"]
    sub = store.one(
        "SELECT COUNT(*) n, COALESCE(SUM(c.total),0) total FROM "
        "(SELECT application_id, SUM(cost_usd) total FROM application_costs GROUP BY application_id) c "
        "JOIN applications a ON a.id=c.application_id WHERE a.status='submitted'"
    ) or {"n": 0, "total": 0}
    return {
        "applications": apps,            # the sample size
        "runs": t["runs"],
        "total_usd": round(t["total"], 4),
        "average_usd": round(t["total"] / apps, 4) if apps else None,
        "submitted_applications": sub["n"],
        "average_per_submitted_usd": round(sub["total"] / sub["n"], 4) if sub["n"] else None,
    }
