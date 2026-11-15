"""Shared fixtures. Every test runs against a fresh data home; nothing touches ~/.applyfirst."""
import pytest

from applyfirst import claude, config, store


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch):
    """A test never reaches the real Claude Code, even on a machine that has it installed.
    A test that needs Claude fakes claude.run, or the process start underneath it."""
    import os
    import subprocess
    real_run = subprocess.run
    claude_exe = os.path.basename(str(claude.shutil.which("claude") or "claude")).lower()

    def guarded(cmd, *a, **k):
        first = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else str(cmd).split(" ")[0]
        name = os.path.basename(str(first)).lower()
        version_only = isinstance(cmd, (list, tuple)) and "--version" in cmd
        if name in (claude_exe, "claude", "claude.cmd", "claude.exe") and not version_only:
            raise AssertionError("a test tried to start the real Claude Code; fake claude.run or subprocess.run")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(claude, "available", lambda: False)
    monkeypatch.setattr(subprocess, "run", guarded)

ALEX = {
    "name": {"first": "Alex", "last": "Rivera", "preferred": ""},
    "email": "alex.rivera@example.com",
    "phone": "555-0100",
    "location": {"city": "Toronto", "region": "Ontario", "country": "CA", "postal_code": ""},
    "links": {"linkedin": "", "github": "https://github.com/example", "portfolio": "", "other": []},
    "education": [{
        "school": "Example University", "degree": "BEng", "field": "Computer Engineering",
        "start": "2024-09", "end": "2028-04", "gpa": "3.6", "gpa_scale": "4.0", "current": True,
    }],
    "work_authorization": {"CA": {"authorized": True, "needs_sponsorship": False},
                           "US": {"authorized": False, "needs_sponsorship": True}},
    "citizenship": ["CA"],
    "languages": [{"language": "English", "level": "Native"}],
    "availability": {"earliest_start": "2027-05-01", "term_months": [4, 8, 12], "willing_to_relocate": True},
    "salary": {"currency": "CAD", "hourly_min": 25, "annual_min": None},
    "demographics": {"gender": "", "pronouns": "", "ethnicity": "", "disability": "", "veteran": ""},
}


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLYFIRST_HOME", str(tmp_path))
    monkeypatch.setenv("APPLYFIRST_NO_SCHEDULER", "1")
    store.reset()
    store.db()
    yield tmp_path
    store.reset()


@pytest.fixture
def alex(tmp_home):
    config.save_profile(ALEX)
    s = config.load_settings()
    s["search"]["countries"] = ["CA"]
    s["search"]["regions"] = ["Ontario"]
    config.save_settings(s)
    return ALEX
