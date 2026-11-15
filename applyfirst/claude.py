"""Run Claude Code headless for the steps that need judgment or a browser.

Every call records what it cost (Claude Code's JSON output carries total_cost_usd and
turn counts) so the product can show the real cost per application.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any

from . import config, store


@dataclass
class Result:
    ok: bool
    text: str = ""
    structured: Any = None
    cost_usd: float = 0.0
    turns: int = 0
    error: str = ""
    raw: dict = field(default_factory=dict)


def available() -> bool:
    cmd = config.get(config.load_settings(), "claude.command", "claude")
    return shutil.which(cmd) is not None


MIN_VERSION = (2, 1, 0)   # needs --chrome, --tools, --json-schema, --max-budget-usd, dontAsk
_version_cache: dict = {}


def version_info() -> dict:
    """{installed, version, ok} for the status screen. Cached for the life of the process."""
    if _version_cache:
        return _version_cache
    exe = shutil.which(config.get(config.load_settings(), "claude.command", "claude"))
    info = {"installed": bool(exe), "version": "", "ok": False}
    if exe:
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout
            import re
            m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
            if m:
                info["version"] = m.group(0)
                info["ok"] = tuple(int(x) for x in m.groups()) >= MIN_VERSION
        except (OSError, subprocess.TimeoutExpired):
            pass
    _version_cache.update(info)
    return info


def run(
    prompt: str,
    run_id: str | None = None,
    *,
    browser: str | None = None,          # None | "chrome-extension" | "playwright"
    allowed_tools: list[str] | None = None,
    json_schema: dict | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    cwd: str | None = None,
    timeout: int = 1800,
) -> Result:
    s = config.load_settings()
    left = budget_left(s)
    if left is not None and left <= 0:
        cap = config.get(s, "claude.daily_budget_usd")
        return Result(False, error=f"Today's Claude spending limit (${cap:.2f}) is used up. "
                                   "Raise it in Settings or wait until tomorrow.")
    exe = config.get(s, "claude.command", "claude")
    # On Windows npm installs claude as a .CMD shim, which subprocess only runs by full path.
    exe = shutil.which(exe) or exe
    cmd = [exe, "-p", "--output-format", "json"]
    cmd += ["--model", model or config.get(s, "claude.model", "sonnet")]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]
    if left is not None:
        cmd += ["--max-budget-usd", f"{left:.2f}"]
    # Locked down: job postings are untrusted text that goes into the prompt, so the background
    # Claude gets no shell, no file reading or writing and no web fetching. A browser run gets
    # the browser tools (and ToolSearch, which loads them); anything else is refused without a
    # prompt ("dontAsk").
    cmd += ["--tools", "ToolSearch" if browser else ""]
    allowed = list(allowed_tools or [])
    if browser == "chrome-extension":
        allowed.append("mcp__claude-in-chrome__*")
    elif browser == "playwright":
        allowed.append("mcp__playwright__*")
    if allowed:
        cmd += ["--allowedTools", *allowed]
    cmd += ["--permission-mode", "dontAsk"]
    tmp_files: list[str] = []
    if browser == "chrome-extension":
        cmd += ["--chrome"]
    elif browser == "playwright":
        profile_dir = str(config.path("browser-profile"))
        mcp = {"mcpServers": {"playwright": {
            "command": "npx",
            "args": ["@playwright/mcp@latest", "--user-data-dir", profile_dir],
        }}}
        fd, p = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(mcp, f)
        tmp_files.append(p)
        cmd += ["--mcp-config", p]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]

    if run_id:
        store.log(run_id, f"claude: starting ({len(prompt)} chars, browser={browser})")
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=timeout, cwd=cwd or str(config.home()),
        )
    except FileNotFoundError:
        return Result(False, error="Claude Code is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        return Result(False, error=f"Claude Code did not finish within {timeout} seconds.")
    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass

    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        data = {}
    res = Result(
        ok=proc.returncode == 0 and not data.get("is_error", False),
        text=data.get("result", "") or proc.stdout,
        structured=data.get("structured_output"),
        cost_usd=float(data.get("total_cost_usd") or 0.0),
        turns=int(data.get("num_turns") or 0),
        error="" if proc.returncode == 0 else (proc.stderr.strip()[-2000:] or "Claude Code exited with an error."),
        raw=data,
    )
    if res.structured is None and json_schema and res.text:
        try:
            res.structured = json.loads(res.text)
        except json.JSONDecodeError:
            pass
    record_spend(res.cost_usd, run_id or "")
    if run_id:
        store.log(run_id, f"claude: ok={res.ok} turns={res.turns} cost_usd={res.cost_usd:.4f} {res.error[:300]}")
    return res


# --------------------------------------------------------------------------- spending cap


def spent_today() -> float:
    """Claude spend since local midnight, from every call this app made."""
    from datetime import datetime

    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    r = store.one("SELECT COALESCE(SUM(usd), 0) s FROM claude_spend WHERE at >= ?",
                  (midnight.isoformat(timespec="seconds"),))
    return float(r["s"] if r else 0.0)


def budget_left(settings: dict | None = None) -> float | None:
    """Dollars left today, or None when there is no cap."""
    cap = config.get(settings or config.load_settings(), "claude.daily_budget_usd")
    if not cap:
        return None
    return max(0.0, float(cap) - spent_today())


def record_spend(usd: float, run_id: str) -> None:
    if usd:
        from datetime import datetime
        store.execute("INSERT INTO claude_spend (at, usd, run_id) VALUES (?,?,?)",
                      (datetime.now().astimezone().isoformat(timespec="seconds"), usd, run_id))
