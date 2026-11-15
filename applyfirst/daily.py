"""The daily routine (sweep, apply in auto mode, read replies) and the in-app scheduler.

The scheduler runs only while `applyfirst` (the app) is open. For runs while it is closed,
schedule `applyfirst daily` with the system scheduler; the README says how.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from . import config, jobs, store


def routine(run_id: str) -> str:
    parts = []
    from .sources import sweep

    parts.append("Find: " + (sweep(run_id) or "done"))
    if config.get(config.load_settings(), "apply.mode") == "auto":
        from .apply import apply_queue

        parts.append("Apply: " + (apply_queue(run_id) or "done"))
    if config.get(config.load_settings(), "tracker.email.enabled"):
        from .tracker import sync

        parts.append("Replies: " + (sync(run_id) or "done"))
    return " | ".join(parts)


def _ran_today() -> bool:
    r = store.one(
        "SELECT started_at FROM runs WHERE kind='daily' ORDER BY started_at DESC LIMIT 1"
    )
    if not r:
        return False
    started = datetime.fromisoformat(r["started_at"]).astimezone()
    return started.date() == datetime.now().astimezone().date()


def _due(now: datetime, hhmm: str) -> bool:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        h, m = 8, 0
    return (now.hour, now.minute) >= (h, m)


def tick() -> str | None:
    s = config.load_settings()
    if not config.get(s, "schedule.run_daily"):
        return None
    if not _due(datetime.now(), config.get(s, "schedule.time", "08:00")) or _ran_today():
        return None
    if "daily" in jobs.running():
        return None
    return jobs.spawn("daily", routine)


def start_scheduler(interval: int = 60) -> threading.Thread:
    def loop() -> None:
        while True:
            try:
                tick()
            except Exception as e:  # never kill the app; the failure is visible in Activity
                rid = store.start_run("daily")
                store.finish_run(rid, f"Scheduler failed to start the daily run: {e}", ok=False)
            time.sleep(interval)

    t = threading.Thread(target=loop, name="scheduler", daemon=True)
    t.start()
    return t
