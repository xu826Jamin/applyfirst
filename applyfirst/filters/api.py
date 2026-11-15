"""Routes mounted at /api/filters: the queue, approve or skip a posting, re-run the filters."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import config, jobs, store
from . import core
from .text import clip

router = APIRouter()

ACTIONS = {"approve": "approved", "skip": "skipped", "reset": ""}


class ActionBody(BaseModel):
    action: str


def _card(p: dict) -> dict:
    """A posting for a list: everything the screen shows, a short snippet instead of the body."""
    out = {k: v for k, v in p.items() if k not in ("raw", "description")}
    out["snippet"] = clip(p.get("description"), 280)
    return out


def _full(p: dict) -> dict:
    out = dict(p)
    out.pop("raw", None)
    return out


@router.get("/queue")
def get_queue(view: str = Query("kept"), limit: int = Query(100, ge=1, le=1000)) -> dict:
    if view not in core.VIEWS:
        raise HTTPException(422, f"view must be one of {', '.join(core.VIEWS)}")
    settings = config.load_settings()
    items = core.queue(settings, view, limit)
    return {"view": view, "total": len(core.view_rows(view)), "counts": core.counts(),
            "postings": [_card(p) for p in items]}


@router.get("/postings/{posting_id:path}")
def get_posting(posting_id: str) -> dict:
    row = store.one("SELECT * FROM postings WHERE id=?", (posting_id,))
    if not row:
        raise HTTPException(404, "No such posting")
    return _full(core._with_reasons(row))


@router.post("/postings/{posting_id:path}/action")
def post_action(posting_id: str, body: ActionBody) -> dict:
    if body.action not in ACTIONS:
        raise HTTPException(422, "action must be approve, skip or reset")
    row = store.one("SELECT id FROM postings WHERE id=?", (posting_id,))
    if not row:
        raise HTTPException(404, "No such posting")
    store.execute("UPDATE postings SET user_action=? WHERE id=?", (ACTIONS[body.action], posting_id))
    return _full(core._with_reasons(store.one("SELECT * FROM postings WHERE id=?", (posting_id,))))


@router.post("/reevaluate")
def reevaluate() -> dict:
    result: dict = {}

    def work(run_id: str) -> str:
        result.update(core.evaluate_all(run_id))
        return result["summary"]

    run_id, summary, ok = jobs.run_now("filter", work)
    if not ok:
        raise HTTPException(500, summary)
    return {"run_id": run_id, "summary": summary, **result}
