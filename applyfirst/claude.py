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
from pathlib import Path
from typing import Any

from . import config, store


def read_rule(path: str) -> str:
    """A Claude Code permission rule allowing Read of exactly this absolute file.
    Absolute paths in rules start with //: C:\\a\\b.pdf -> Read(//c/a/b.pdf), /a/b -> Read(//a/b)."""
    p = Path(os.path.abspath(path))
    drive = p.drive.rstrip(":").lower()
    rest = p.as_posix()[len(p.drive):].lstrip("/")
    return f"Read(//{drive}/{rest})" if drive else f"Read(//{rest})"


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


EXTENSION_ID = "fcoeoabgfenejglbffodgkkbkcdhcgfn"            # Claude in Chrome, Chrome Web Store
NATIVE_HOST = "com.anthropic.claude_code_browser_extension"  # written by `claude --chrome`


def _chrome_user_data() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(local) / "Google" / "Chrome" / "User Data"
    if os.uname().sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "google-chrome"


def _chrome_exe_found() -> bool:
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    paths = [
        rf"{pf}\Google\Chrome\Application\chrome.exe",
        rf"{pf86}\Google\Chrome\Application\chrome.exe",
        rf"{local}\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app",
        str(Path.home() / "Applications" / "Google Chrome.app"),
    ]
    if any(os.path.exists(p) for p in paths):
        return True
    return any(shutil.which(n) for n in ("google-chrome", "google-chrome-stable"))


def _native_host_registered(user_data: Path) -> bool:
    if os.name == "nt":
        import winreg
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                           rf"Software\Google\Chrome\NativeMessagingHosts\{NATIVE_HOST}"))
            return True
        except OSError:
            return False
    return (user_data / "NativeMessagingHosts" / f"{NATIVE_HOST}.json").exists()


def chrome_info(user_data: Path | None = None) -> dict:
    """{chrome, extension, connected} for the status screen: is Chrome installed, is Claude in
    Chrome added to any Chrome profile, and has `claude --chrome` been run so Claude Code can reach
    it. Plain file and registry reads, so it is not cached: a reload after setup clears the notice."""
    ud = user_data or _chrome_user_data()
    chrome = ud.is_dir() or _chrome_exe_found()
    extension = False
    if ud.is_dir():
        for prof in ud.iterdir():
            if (prof / "Extensions" / EXTENSION_ID).is_dir():
                extension = True
                break
    connected = _native_host_registered(ud)
    return {"chrome": chrome, "extension": extension, "connected": connected}


# Every run in the person's own Chrome opens its tabs in a new tab group. Chrome removes a group
# when its last tab closes, so closing the tabs is what cleans the group up.
CHROME_TABS_RULE = (
    "TABS: this is the person's own Chrome. Open what you need in new tabs and never touch tabs\n"
    "they already had open. Before you give your final answer, close every tab you opened with\n"
    "tabs_close_mcp, so the tab group you worked in disappears with them. The only exception is\n"
    "a tab these instructions tell you to leave open: leave that one and close all the others."
)


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
    upload_files: list[str] | None = None,   # files the browser may attach (resume, cover letter)
    mcp_servers: dict | None = None,         # extra MCP servers {name: config}; all their tools allowed
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
    # Claude in Chrome's file_upload only attaches files the session may Read (Claude Code
    # 2.1.325, seen 2026-11-15). So a run with files to attach gets the Read tool, allowed for
    # exactly those files; any other read is refused by "dontAsk".
    # Each file under its given path and, when a symlink is involved (macOS /tmp, /home), its real one.
    uploads = list(dict.fromkeys(
        p for f in (upload_files or []) if f for p in (os.path.abspath(f), os.path.realpath(f)))) if browser else []
    tools = ["ToolSearch"] if browser else []
    if uploads:
        tools.append("Read")
    cmd += ["--tools", ",".join(tools)]
    allowed = list(allowed_tools or [])
    allowed += [read_rule(f) for f in uploads]
    if browser == "chrome-extension":
        allowed.append("mcp__claude-in-chrome__*")
    elif browser == "playwright":
        allowed.append("mcp__playwright__*")
    servers = dict(mcp_servers or {})
    allowed += [f"mcp__{name}__*" for name in servers]
    if allowed:
        cmd += ["--allowedTools", *allowed]
    cmd += ["--permission-mode", "dontAsk"]
    tmp_files: list[str] = []
    if browser == "chrome-extension":
        cmd += ["--chrome"]
    elif browser == "playwright":
        profile_dir = str(config.path("browser-profile"))
        servers["playwright"] = {
            "command": "npx",
            "args": ["@playwright/mcp@latest", "--user-data-dir", profile_dir],
        }
    if servers:
        mcp = {"mcpServers": servers}
        fd, p = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(mcp, f)
        tmp_files.append(p)
        cmd += ["--mcp-config", p]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]

    if run_id:
        store.log(run_id, f"claude: starting ({len(prompt)} chars, browser={browser})")
    if browser == "chrome-extension":
        prompt = prompt.rstrip() + "\n\n" + CHROME_TABS_RULE
    # With Read switched on, Claude Code also reads anything under its working directory without
    # asking. The applyfirst home holds the profile and the email password, so a run that can Read
    # starts in an empty folder of its own; the files to attach are allowed one by one above.
    sandbox = tempfile.mkdtemp(prefix="applyfirst-run-") if uploads and not cwd else None
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=timeout, cwd=cwd or sandbox or str(config.home()),
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
        if sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)

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
