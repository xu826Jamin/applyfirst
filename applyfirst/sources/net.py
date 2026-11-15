"""Polite HTTP for a sweep of thousands of boards.

Two rules: no single host is hammered, and a failure is a counted failure, never silence.

Pacing is per host. Hosts shared by many boards (boards-api.greenhouse.io serves every
Greenhouse board) can take a steady trickle from many threads; a host that belongs to one
employer (acme.wd5.myworkdayjobs.com) gets a slower gap, because every request on it is one
company's server. Thousands of boards still finish in minutes because the threads spend their
time on different hosts.
"""
from __future__ import annotations

import gzip
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

UA = "applyfirst/0.1 (open-source job search tool; polls public job-board APIs)"
TIMEOUT = 25

# Shared API hosts that front many boards, and the gap between requests to them.
SHARED_HOSTS = {
    "boards-api.greenhouse.io": 0.05,
    "api.lever.co": 0.05,
    "api.ashbyhq.com": 0.05,
    "api.smartrecruiters.com": 0.05,
    "apply.workable.com": 0.10,
    "api.rippling.com": 0.10,
    "raw.githubusercontent.com": 0.0,
}
DEFAULT_GAP = 0.5   # at most 2 requests a second to any one employer's own host


class FetchError(Exception):
    """A board could not be read. `kind` is a short stable word used in the sweep report."""

    def __init__(self, message: str, kind: str = "error", status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


class Pacer:
    """Per-host minimum gap between requests, safe across threads."""

    def __init__(self, gaps: dict[str, float] | None = None, default: float = DEFAULT_GAP,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.gaps = dict(SHARED_HOSTS if gaps is None else gaps)
        self.default = default
        self.clock = clock
        self.sleep = sleep
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def gap_for(self, host: str) -> float:
        return self.gaps.get(host, self.default)

    def wait(self, host: str) -> float:
        """Block until this host may be used again. Returns the seconds slept."""
        gap = self.gap_for(host)
        if gap <= 0:
            return 0.0
        with self._lock:
            now = self.clock()
            at = max(now, self._next.get(host, 0.0))
            self._next[host] = at + gap
        delay = at - now
        if delay > 0:
            self.sleep(delay)
        return max(delay, 0.0)


class Http:
    """GET/POST JSON or text with pacing, one polite retry on 429/503, and clear errors."""

    def __init__(self, pacer: Pacer | None = None, opener: Callable[..., Any] | None = None,
                 timeout: int = TIMEOUT):
        self.pacer = pacer or Pacer()
        self._open = opener or urllib.request.urlopen
        self.timeout = timeout
        self.requests = 0
        self._count_lock = threading.Lock()

    def _request(self, url: str, data: bytes | None, headers: dict[str, str]) -> tuple[bytes, str]:
        host = urllib.parse.urlparse(url).hostname or ""
        h = {"User-Agent": UA, "Accept-Encoding": "gzip", **headers}
        for attempt in (0, 1):
            self.pacer.wait(host)
            with self._count_lock:
                self.requests += 1
            req = urllib.request.Request(url, data=data, headers=h)
            try:
                with self._open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                        try:
                            raw = gzip.decompress(raw)
                        except OSError:
                            pass
                    return raw, resp.geturl()
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt == 0:
                    try:
                        wait = min(float(e.headers.get("Retry-After") or 2), 10.0)
                    except (TypeError, ValueError):
                        wait = 2.0
                    self.pacer.sleep(wait)
                    continue
                kind = "rate-limited" if e.code == 429 else f"http{e.code}"
                raise FetchError(f"HTTP {e.code} from {host}", kind, e.code) from e
            except urllib.error.URLError as e:
                raise FetchError(f"could not reach {host}: {e.reason}", "unreachable") from e
            except (TimeoutError, OSError) as e:
                raise FetchError(f"timed out or dropped by {host}: {e}", "unreachable") from e
        raise FetchError(f"gave up on {host}", "rate-limited", 429)

    def text(self, url: str, headers: dict[str, str] | None = None) -> str:
        raw, _ = self._request(url, None, headers or {})
        return raw.decode("utf-8", "replace")

    def json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        raw, _ = self._request(url, None, {"Accept": "application/json", **(headers or {})})
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            raise FetchError(f"{urllib.parse.urlparse(url).hostname} did not return JSON",
                             "bad-response") from e

    def post_json(self, url: str, payload: dict, headers: dict[str, str] | None = None) -> Any:
        raw, _ = self._request(
            url, json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json", "Accept": "application/json", **(headers or {})})
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            raise FetchError(f"{urllib.parse.urlparse(url).hostname} did not return JSON",
                             "bad-response") from e

    def final_url(self, url: str) -> tuple[str, str]:
        """GET a page; returns (final_url_after_redirects, body_text)."""
        raw, final = self._request(url, None, {"Accept": "text/html,*/*"})
        return final, raw.decode("utf-8", "replace")
