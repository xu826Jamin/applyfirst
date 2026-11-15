"""Shared helpers for the apply tests: fake sibling packages, fake Claude, posting rows."""
from __future__ import annotations

import sys
import types

import pytest

from applyfirst import claude, config, store


def add_posting(pid="greenhouse:1", company="Acme", title=None, **over):
    row = {
        "id": pid, "source": "greenhouse", "company": company, "title": title or f"Role {pid}",
        "location": "Toronto, ON", "country": "CA", "url": f"https://boards.example.com/{pid}",
        "apply_url": f"https://boards.example.com/{pid}/apply", "ats": "greenhouse",
        "description": "Build things. Pay range: $24.00 - $32.00 per hour.",
        "first_seen_at": store.now(), "verdict": "keep", "user_action": "", "alive": 1,
    }
    row.update(over)
    store.upsert("postings", row)
    return row


def result(status="ready-to-submit", cost=0.5, **extra):
    data = {"status": status, "notes": "", "pending_questions": [], "answers_used": []}
    data.update(extra)
    return claude.Result(ok=True, structured=data, cost_usd=cost, turns=12)


@pytest.fixture
def fakes(alex, monkeypatch, tmp_path):
    """Fake filters and resume packages plus a recording fake claude.run."""
    resume = tmp_path / "Alex_Rivera_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")

    def queue(settings, view="kept", limit=100):
        if view == "approved":
            sql = "SELECT * FROM postings WHERE user_action='approved' ORDER BY first_seen_at, id"
        else:
            sql = "SELECT * FROM postings WHERE verdict='keep' AND user_action='' ORDER BY first_seen_at, id"
        return store.rows(sql)[:limit]

    filters = types.ModuleType("applyfirst.filters")
    filters.queue = queue
    res = types.ModuleType("applyfirst.resume")
    res.resume_for = lambda posting, settings: str(resume)
    res.cover_letter = lambda posting, run_id=None: None
    monkeypatch.setitem(sys.modules, "applyfirst.filters", filters)
    monkeypatch.setitem(sys.modules, "applyfirst.resume", res)

    state = types.SimpleNamespace(calls=[], results=[], resume=resume, resume_mod=res)

    def fake_run(prompt, run_id=None, **kw):
        state.calls.append({"prompt": prompt, "run_id": run_id, **kw})
        nxt = state.results.pop(0) if state.results else result()
        return nxt

    monkeypatch.setattr(claude, "run", fake_run)
    return state


def set_settings(**apply):
    s = config.load_settings()
    s["apply"].update(apply)
    config.save_settings(s)
    return config.load_settings()
