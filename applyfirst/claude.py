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
    cmd = [config.get(s, "claude.command", "claude"), "-p", "--output-format", "json"]
    cmd += ["--model", model or config.get(s, "claude.model", "sonnet")]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]
    if allowed_tools:
        cmd += ["--allowedTools", *allowed_tools]
    # Headless runs cannot answer permission prompts; the allowed tool list is the boundary.
    cmd += ["--permission-mode", "bypassPermissions"]
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
    if run_id:
        store.log(run_id, f"claude: ok={res.ok} turns={res.turns} cost_usd={res.cost_usd:.4f} {res.error[:300]}")
    return res
