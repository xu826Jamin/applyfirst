"""HTTP routes for the sources package, mounted at /api/sources."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import jobs
from . import boards
from .boards import discover
from .net import FetchError
from .run import add_manual, sweep

router = APIRouter()


class ManualBody(BaseModel):
    url: str


@router.post("/sweep")
def start_sweep() -> dict:
    try:
        return {"run_id": jobs.spawn("sweep", sweep)}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/discover")
def start_discover() -> dict:
    try:
        return {"run_id": jobs.spawn("discover", discover)}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/manual")
def manual(body: ManualBody) -> dict:
    try:
        return add_manual(body.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FetchError as e:
        raise HTTPException(status_code=502, detail=f"Could not open that link: {e}")


@router.get("/boards")
def board_counts() -> dict:
    """Boards the sweep reads, counted by the system they run on."""
    return boards.counts()
