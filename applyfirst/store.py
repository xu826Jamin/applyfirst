"""SQLite store shared by every package. Thin on purpose: plain SQL, dict rows."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config

PKG = Path(__file__).parent


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    p = db_path or config.path("applyfirst.sqlite")
    con = sqlite3.connect(p, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript((PKG / "schema.sql").read_text(encoding="utf-8"))
    for extra in sorted(PKG.glob("*/schema.sql")):
        con.executescript(extra.read_text(encoding="utf-8"))
    con.commit()


_con: sqlite3.Connection | None = None


def reset() -> None:
    """Drop the shared connection (tests point APPLYFIRST_HOME elsewhere, then call this)."""
    global _con
    if _con is not None:
        _con.close()
    _con = None


def db() -> sqlite3.Connection:
    """Process-wide connection, initialised on first use."""
    global _con
    if _con is None:
        _con = connect()
        init(_con)
    return _con


def rows(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    return [dict(r) for r in db().execute(sql, tuple(params)).fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    r = db().execute(sql, tuple(params)).fetchone()
    return dict(r) if r else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    cur = db().execute(sql, tuple(params))
    db().commit()
    return cur.lastrowid or cur.rowcount


def upsert(table: str, row: dict, key: str = "id") -> None:
    """Insert, or update the given columns of an existing row. JSON-encodes dict/list values."""
    vals = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
    cols = ", ".join(vals)
    marks = ", ".join("?" for _ in vals)
    updates = ", ".join(f"{c}=excluded.{c}" for c in vals if c != key)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT({key}) DO UPDATE SET {updates}"
    db().execute(sql, tuple(vals.values()))
    db().commit()


# --------------------------------------------------------------------------- runs


def start_run(kind: str) -> str:
    rid = f"{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    log = config.path("runs") / f"{rid}.log"
    execute(
        "INSERT INTO runs (id, kind, status, started_at, log_file) VALUES (?,?,?,?,?)",
        (rid, kind, "running", now(), str(log)),
    )
    return rid


def log(run_id: str, line: str) -> None:
    r = one("SELECT log_file FROM runs WHERE id=?", (run_id,))
    if r and r["log_file"]:
        with open(r["log_file"], "a", encoding="utf-8") as f:
            f.write(f"{now()} {line}\n")


def finish_run(run_id: str, summary: str, ok: bool = True) -> None:
    execute(
        "UPDATE runs SET status=?, finished_at=?, summary=? WHERE id=?",
        ("done" if ok else "failed", now(), summary, run_id),
    )
