"""The applyfirst Chrome window: a browser applyfirst opens and owns, so applying needs no extension.

It is Chrome (or Edge, or Chromium) started on its own profile folder inside the applyfirst home,
with a debugging port bound to this computer only. Claude connects to that port through the
Playwright MCP server. The window stays open after a Claude run ends, so in review mode the filled
form is still there to read and submit, and the sign-ins the person makes in it are kept for next
time. The person's own Chrome profile is never touched.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from . import config
from .resume import render

PREFERRED_PORT = 9333
STATE_FILE = "browser-window.json"       # {"port": int}: which port our window listens on
PROFILE_DIR = "browser-window"           # the window's own Chrome profile, under the applyfirst home
START_TIMEOUT = 25                       # seconds to wait for a freshly started window to answer

NO_BROWSER = ("applyfirst could not find Chrome, Edge or Chromium on this computer. Install Chrome "
              "(google.com/chrome), then reload this page.")
NO_NODE = "Node.js is not installed. Install it from nodejs.org, then reload this page."


def profile_dir() -> Path:
    return config.path(PROFILE_DIR)


def node_ok() -> bool:
    """Claude reaches the window through `npx @playwright/mcp`, which needs Node.js."""
    return bool(shutil.which("npx"))


def alive(port: int, timeout: float = 1.5) -> bool:
    """Is a Chrome answering on the debugging port? Only ever asks 127.0.0.1."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/json/version", timeout=timeout) as r:
            return "Browser" in json.loads(r.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return False


def _saved_port() -> int | None:
    try:
        with open(config.path(STATE_FILE), encoding="utf-8") as f:
            port = int(json.load(f).get("port"))
        return port if 0 < port < 65536 else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _free_port() -> int:
    """The preferred port when nothing uses it, else any free one."""
    for candidate in (PREFERRED_PORT, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return s.getsockname()[1]
    raise OSError("no free local port")


def launch_command(exe: str, port: int, profile: str) -> list[str]:
    return [
        exe,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]


def _start(cmd: list[str]) -> None:
    """Start the window detached, so it outlives this process and every Claude run."""
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


def _ensure(timeout: float = START_TIMEOUT) -> tuple[int | None, str]:
    """(port, '') once the window is listening, starting it when needed; (None, why) when it cannot."""
    port = _saved_port()
    if port and alive(port):
        return port, ""
    exe = render.find_browser()
    if not exe:
        return None, NO_BROWSER
    try:
        port = _free_port()
        profile = profile_dir()
        profile.mkdir(parents=True, exist_ok=True)
        _start(launch_command(exe, port, str(profile)))
    except OSError as e:
        return None, f"applyfirst could not open its Chrome window: {e}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if alive(port):
            tmp = config.path(STATE_FILE).with_suffix(".tmp")
            tmp.write_text(json.dumps({"port": port}), encoding="utf-8")
            os.replace(tmp, config.path(STATE_FILE))
            return port, ""
        time.sleep(0.4)
    return None, "applyfirst's Chrome window did not start. Close any leftover Chrome windows it opened and try again."


def ensure_window() -> tuple[int | None, str]:
    """What claude.run calls before a run on the own-window route."""
    return _ensure()


def mcp_config(port: int) -> dict:
    """The Playwright MCP server, attached to the window over its debugging port."""
    return {
        "command": shutil.which("npx") or "npx",
        "args": ["@playwright/mcp@latest", "--cdp-endpoint", f"http://127.0.0.1:{int(port)}"],
    }
