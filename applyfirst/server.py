"""The local web app: JSON API under /api, the interface from web/ at /.

Each package adds its own routes in applyfirst/<package>/api.py as `router`
(a FastAPI APIRouter); they are mounted at /api/<package>. This file holds only the
shared routes: profile, settings, status, runs.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, jobs, store

PACKAGES = ["sources", "filters", "resume", "apply", "tracker"]
WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="applyfirst", docs_url="/api/docs")


@app.on_event("startup")
def _start_scheduler() -> None:
    import os

    if os.environ.get("APPLYFIRST_NO_SCHEDULER"):
        return
    from .daily import start_scheduler

    start_scheduler()


@app.post("/api/daily")
def run_daily_now() -> dict:
    from .daily import routine

    try:
        return {"run_id": jobs.spawn("daily", routine)}
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.get("/api/profile")
def get_profile() -> dict:
    return config.load_profile()


@app.put("/api/profile")
def put_profile(body: dict) -> dict:
    return config.save_profile(body)


@app.get("/api/settings")
def get_settings() -> dict:
    return {"settings": config.load_settings(), "warnings": config.WARNINGS}


@app.put("/api/settings")
def put_settings(body: dict) -> dict:
    return {"settings": config.save_settings(body), "warnings": config.WARNINGS}


@app.put("/api/secrets/{key}")
def put_secret(key: str, body: dict) -> dict:
    config.save_secret(key, str(body.get("value", "")))
    return {"ok": True}


@app.get("/api/secrets")
def list_secrets() -> dict:
    # Which secrets are set, never their values.
    return {k: bool(v) for k, v in config.load_secrets().items()}


@app.get("/api/status")
def status() -> dict:
    count = lambda sql: (store.one(sql) or {}).get("n", 0)  # noqa: E731
    return {
        "set_up": config.is_set_up(),
        "postings": count("SELECT COUNT(*) n FROM postings WHERE duplicate_of='' AND alive=1"),
        "kept": count("SELECT COUNT(*) n FROM postings WHERE verdict='keep' AND duplicate_of='' AND alive=1"),
        "new_today": count(
            "SELECT COUNT(*) n FROM postings WHERE verdict='keep' AND first_seen_at >= datetime('now','-1 day')"
        ),
        "applied": count("SELECT COUNT(*) n FROM applications WHERE status='submitted'"),
        "needs_you": count("SELECT COUNT(*) n FROM applications WHERE status IN ('needs-you','ready-to-submit')"),
        "interviews": count(
            "SELECT COUNT(*) n FROM applications WHERE outcome IN ('assessment','interview','offer')"
        ),
        "pending_questions": count("SELECT COUNT(*) n FROM answers WHERE pending=1"),
        "running": jobs.running(),
        "last_runs": store.rows("SELECT * FROM runs ORDER BY started_at DESC LIMIT 10"),
    }


@app.get("/api/runs")
def runs(limit: int = 50) -> list[dict]:
    return store.rows("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))


@app.get("/api/runs/{run_id}/log", response_class=PlainTextResponse)
def run_log(run_id: str) -> str:
    r = store.one("SELECT log_file FROM runs WHERE id=?", (run_id,))
    if not r:
        raise HTTPException(404, "No such run.")
    p = Path(r["log_file"])
    # The job may be mid-write; a cut multi-byte character must not fail the request.
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


for _name in PACKAGES:
    try:
        _mod = importlib.import_module(f"applyfirst.{_name}.api")
    except ModuleNotFoundError as e:
        if e.name != f"applyfirst.{_name}.api":
            raise
        continue
    app.include_router(_mod.router, prefix=f"/api/{_name}", tags=[_name])


if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")
