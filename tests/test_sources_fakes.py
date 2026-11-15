"""A stand-in for the network, shared by the sources tests. No test in this file."""
from __future__ import annotations

from applyfirst.sources.net import FetchError


class FakeHttp:
    """Answers from a table of url -> value. A value that is a FetchError is raised; a callable
    is called with (url, payload). Unknown URLs are a 404, so a test never silently hits the web."""

    def __init__(self, routes: dict | None = None):
        self.routes = routes if routes is not None else {}
        self.calls: list[tuple[str, object]] = []

    def _answer(self, url, payload=None):
        self.calls.append((url, payload))
        hit = self.routes.get(url)
        if hit is None:
            for prefix, val in self.routes.items():
                if prefix.endswith("*") and url.startswith(prefix[:-1]):
                    hit = val
                    break
        if hit is None:
            raise FetchError(f"no route for {url}", "http404", 404)
        if isinstance(hit, Exception):
            raise hit
        if callable(hit):
            return hit(url, payload)
        return hit

    def json(self, url, headers=None):
        return self._answer(url)

    def text(self, url, headers=None):
        return self._answer(url)

    def post_json(self, url, payload, headers=None):
        return self._answer(url, payload)

    def final_url(self, url):
        r = self._answer(url)
        return (url, r) if isinstance(r, str) else r
