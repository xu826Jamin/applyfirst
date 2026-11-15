"""Routes for the tracker, mounted at /api/tracker."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import jobs, store
from . import insights, record, syncer

router = APIRouter()


class OutcomeBody(BaseModel):
    outcome: str


class MatchBody(BaseModel):
    application_id: int


@router.post("/sync")
def post_sync() -> dict:
    try:
        run_id = jobs.spawn("sync", syncer.sync)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"run_id": run_id}


@router.get("/stats")
def get_stats() -> dict:
    return insights.stats()


@router.post("/applications/{app_id}/outcome")
def post_outcome(app_id: int, body: OutcomeBody) -> dict:
    try:
        return record.set_manual_outcome(app_id, body.outcome.strip().lower())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.get("/messages")
def get_messages(unmatched: int = 0, limit: int = 200) -> list[dict]:
    return record.list_messages(unmatched=bool(unmatched), limit=max(1, min(limit, 1000)))


@router.post("/messages/{message_id}/match")
def post_match(message_id: int, body: MatchBody) -> dict:
    try:
        return record.match_message(message_id, body.application_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
