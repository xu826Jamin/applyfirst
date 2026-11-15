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


def _hours_since_last(kinds: tuple[str, ...]) -> float | None:
    marks = ",".join("?" * len(kinds))
    r = store.one(f"SELECT started_at FROM runs WHERE kind IN ({marks}) ORDER BY started_at DESC LIMIT 1", kinds)
    if not r:
        return None
    started = datetime.fromisoformat(r["started_at"])
    return (datetime.now(started.tzinfo) - started).total_seconds() / 3600


def _interval_due(kinds: tuple[str, ...], hours: float) -> bool:
    if not hours or hours <= 0:
        return False
    since = _hours_since_last(kinds)
    # Never ran: the user starts the first search from setup; intervals take over after that.
    return since is not None and since >= hours


def tick() -> str | None:
    """Start whatever is due. While the app is open: the daily run at its time, a search every
    sources.sweep_interval_hours (fresh postings are the point), replies every
    tracker.sync_interval_hours. Only one job of each kind at a time."""
    s = config.load_settings()
    busy = set(jobs.running())
    if busy & {"daily", "sweep", "apply"}:
        return None
    if (config.get(s, "schedule.run_daily") and _due(datetime.now(), config.get(s, "schedule.time", "08:00"))
            and not _ran_today()):
        return jobs.spawn("daily", routine)
    if not config.is_set_up():
        return None
    if _interval_due(("sweep", "daily"), float(config.get(s, "sources.sweep_interval_hours", 0) or 0)):
        from .sources import sweep
        return jobs.spawn("sweep", sweep)
    if (config.get(s, "tracker.email.enabled") and "sync" not in busy
            and _interval_due(("sync", "daily"), float(config.get(s, "tracker.sync_interval_hours", 0) or 0))):
        from .tracker import sync
        return jobs.spawn("sync", sync)
    return None


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
