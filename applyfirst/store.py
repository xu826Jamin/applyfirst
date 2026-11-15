"""SQLite store shared by every package. Thin on purpose: plain SQL, dict rows."""
from __future__ import annotations

import json
import sqlite3
import threading
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


def _schema_scripts() -> list[str]:
    files = [PKG / "schema.sql"] + sorted(PKG.glob("*/schema.sql"))
    return [f.read_text(encoding="utf-8") for f in files]


def init(con: sqlite3.Connection) -> None:
    for script in _schema_scripts():
        con.executescript(script)
    upgrade(con)
    con.commit()


def upgrade(con: sqlite3.Connection) -> list[str]:
    """Bring an older database up to the current schema by adding any missing columns.

    CREATE TABLE IF NOT EXISTS never changes a table that already exists, so a new column in a
    later version would otherwise break every existing install. The current schema is built in
    memory and compared table by table. Returns what was added (for tests and logs)."""
    ref = sqlite3.connect(":memory:")
    try:
        for script in _schema_scripts():
            ref.executescript(script)
        added = []
        tables = [r[0] for r in ref.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            have = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            if not have:
                continue
            for _cid, name, ctype, notnull, default, _pk in ref.execute(f"PRAGMA table_info({t})"):
                if name in have:
                    continue
                col = f'"{name}" {ctype or ""}'
                if default is not None:
                    col += f" DEFAULT {default}"
                    if notnull:
                        col += " NOT NULL"
                con.execute(f"ALTER TABLE {t} ADD COLUMN {col}")
                added.append(f"{t}.{name}")
        return added
    finally:
        ref.close()


# One connection per thread: a sqlite3 connection must not be used by two threads at once
# (a sweep writing in the background while the interface reads gave "API misuse" errors).
# WAL mode lets the readers run while one writer works.
_local = threading.local()
_all: list[sqlite3.Connection] = []
_all_lock = threading.Lock()
_initialised: set[str] = set()


def reset() -> None:
    """Close every connection (tests point APPLYFIRST_HOME elsewhere, then call this)."""
    with _all_lock:
        for c in _all:
            try:
                c.close()
            except sqlite3.Error:
                pass
        _all.clear()
        _initialised.clear()
    _local.__dict__.clear()


def db() -> sqlite3.Connection:
    """This thread's connection to the current data home, initialised on first use."""
    p = str(config.path("applyfirst.sqlite"))
    con = getattr(_local, "con", None)
    if con is not None and getattr(_local, "path", None) == p:
        return con
    con = connect(Path(p))
    with _all_lock:
        _all.append(con)
        if p not in _initialised:
            init(con)
            _initialised.add(p)
    _local.con, _local.path = con, p
    return con


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
