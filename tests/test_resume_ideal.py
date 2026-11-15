"""Ideal resume per role group: asked of Claude once per group, cached, and only ever steers which
of the person's own lines are picked."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "resume"))
import bankdata  # noqa: E402

from applyfirst import claude, config  # noqa: E402
from applyfirst.resume import bank, builder, ideal  # noqa: E402


def _fake_claude(monkeypatch, terms):
    calls = []

    def run(prompt, run_id=None, **k):
        calls.append(prompt)
        return claude.Result(True, structured={"terms": terms, "summary": "Lead with shipped code."})

    monkeypatch.setattr(claude, "available", lambda: True)
    monkeypatch.setattr(claude, "run", run)
    return calls


def test_outline_is_asked_once_then_cached(alex, monkeypatch):
    calls = _fake_claude(monkeypatch, ["Python", "Kubernetes"])
    assert ideal.outline("software")["terms"] == ["Python", "Kubernetes"]
    assert ideal.outline("software")["terms"] == ["Python", "Kubernetes"]
    assert len(calls) == 1 and "software engineering" in calls[0]


def test_ideal_terms_map_only_onto_the_persons_own_skills(alex, monkeypatch):
    bankdata.seed()
    entries = bank.load(True)
    _fake_claude(monkeypatch, ["Python", "Haskell compiler design", "Kubernetes"])
    got = ideal.wanted("software", entries)
    vocab = bank.vocabulary(entries)
    assert got and got <= vocab


def test_no_claude_falls_back_without_failing(alex, monkeypatch):
    monkeypatch.setattr(claude, "available", lambda: False)
    assert ideal.outline("hardware") == {}
    assert ideal.wanted("hardware", []) == set()


def test_groups_default_to_search_fields_then_user_pick(alex):
    s = config.load_settings()
    s["search"]["fields"] = ["software", "data-ml"]
    assert ideal.groups(s) == ["software", "data-ml"]
    s["apply"]["resume_groups"] = ["hardware"]
    assert ideal.groups(s) == ["hardware"]


def test_ideal_mode_builds_for_the_postings_group_and_leans_to_the_posting(alex, monkeypatch):
    seen = {}
    monkeypatch.setattr(builder, "build_detailed",
                        lambda role, posting, reuse=False, use_ideal=False: seen.update(role=role, posting=posting, ideal=use_ideal)
                        or builder.BuildResult("x.pdf", "pdf", 1))
    s = config.load_settings()
    s["apply"]["resume_tailoring"] = "ideal"
    s["apply"]["resume_groups"] = ["software", "hardware"]
    p = {"field": "hardware", "title": "FPGA intern"}
    builder.resume_for(p, s)
    assert seen == {"role": "hardware", "posting": p, "ideal": True}
    builder.resume_for({"field": "marketing"}, s)
    assert seen["role"] == "software"          # outside the groups: the first group's version
    s["apply"]["resume_tailoring"] = "by-role-type"   # older setting means the same thing now
    builder.resume_for(p, s)
    assert seen["ideal"] is True
