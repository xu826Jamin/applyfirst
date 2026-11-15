"""Run long work (sweeps, application batches, mail sync) in the background.

Every job is a row in `runs`, writes a log file, and ends as done or failed with a
one-line summary. A job that raises is recorded as failed with the error; nothing fails
silently.
"""
from __future__ import annotations

import threading
import traceback
from typing import Callable

from . import store

_lock = threading.Lock()
_active: dict[str, threading.Thread] = {}


def spawn(kind: str, fn: Callable[[str], str]) -> str:
    """Start fn(run_id) -> summary in a thread. One job per kind at a time."""
    with _lock:
        t = _active.get(kind)
        if t and t.is_alive():
            raise RuntimeError(f"A {kind} is already running.")
        run_id = store.start_run(kind)

        def target() -> None:
            try:
                summary = fn(run_id) or "Done."
                store.finish_run(run_id, summary, ok=True)
            except Exception as e:  # recorded, never swallowed
                store.log(run_id, traceback.format_exc())
                store.finish_run(run_id, f"Failed: {e}", ok=False)

        t = threading.Thread(target=target, name=run_id, daemon=True)
        _active[kind] = t
        t.start()
        return run_id


def run_now(kind: str, fn: Callable[[str], str]) -> tuple[str, str, bool]:
    """Same as spawn but in the foreground (CLI and scheduled runs). Returns (id, summary, ok)."""
    run_id = store.start_run(kind)
    try:
        summary = fn(run_id) or "Done."
        store.finish_run(run_id, summary, ok=True)
        return run_id, summary, True
    except Exception as e:
        store.log(run_id, traceback.format_exc())
        store.finish_run(run_id, f"Failed: {e}", ok=False)
        return run_id, f"Failed: {e}", False


def running() -> list[str]:
    return [k for k, t in _active.items() if t.is_alive()]
