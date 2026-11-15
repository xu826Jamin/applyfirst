"""Shared fixtures. Every test runs against a fresh data home; nothing touches ~/.applyfirst."""
import pytest

from applyfirst import config, store

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
