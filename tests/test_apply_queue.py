import sys
import types

import pytest

from applyfirst import claude, config, store
from applyfirst.apply import apply_queue, learn
from test_apply_support import add_posting, fakes, result, set_settings  # noqa: F401


def approve(*ids):
    for i in ids:
        store.execute("UPDATE postings SET user_action='approved' WHERE id=?", (i,))


def app(pid):
    return store.one("SELECT * FROM applications WHERE posting_id=? ORDER BY id DESC", (pid,))


def test_review_mode_stops_before_submit(fakes, monkeypatch):
    monkeypatch.setattr(claude, "chrome_info", lambda: {"chrome": True, "extension": True, "connected": True})
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("ready-to-submit", cost=0.4)]
    summary = apply_queue("r1")
    row = app("g:1")
    assert row["status"] == "ready-to-submit"
    assert row["resume_file"] == "Alex_Rivera_Resume.pdf"
    assert row["submitted_at"] == ""
    call = fakes.calls[0]
    assert call["browser"] == "chrome-extension"
    assert call["json_schema"]["properties"]["status"]["enum"][0] == "submitted"
    assert call["max_turns"] == 60
    assert "MODE: review" in call["prompt"]
    assert "1 ready for you to review" in summary and "$0.40" in summary


def test_without_the_extension_applications_use_the_applyfirst_window(fakes, monkeypatch):
    monkeypatch.setattr(claude, "chrome_info", lambda: {"chrome": True, "extension": False, "connected": False})
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("ready-to-submit")]
    apply_queue("r1")
    call = fakes.calls[0]
    assert call["browser"] == "own-window"


def test_auto_mode_submits_and_stores_confirmation(fakes):
    set_settings(mode="auto", review_first=0)
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("submitted", confirmation_text="Thanks, your application was received.")]
    apply_queue("r1")
    row = app("g:1")
    assert row["status"] == "submitted" and row["submitted_at"]
    assert "Thanks, your application was received." in row["notes"]
    assert "MODE: auto" in fakes.calls[0]["prompt"]


def test_auto_submitted_without_confirmation_is_not_claimed(fakes):
    set_settings(mode="auto", review_first=0)
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("submitted")]
    apply_queue("r1")
    row = app("g:1")
    assert row["status"] == "needs-you" and "no confirmation" in row["needs_you"]
    assert row["submitted_at"] == ""


def test_review_first_then_auto_and_kept_postings_join(fakes):
    set_settings(mode="auto", review_first=1)
    add_posting("g:1", first_seen_at="2026-01-01T00:00:00+00:00")
    add_posting("g:2", first_seen_at="2026-01-02T00:00:00+00:00")
    add_posting("g:3", first_seen_at="2026-01-03T00:00:00+00:00")   # kept, never approved
    approve("g:1", "g:2")
    fakes.results = [result("ready-to-submit"), result("submitted", confirmation_text="ok"),
                     result("submitted", confirmation_text="ok too")]
    apply_queue("r1")
    assert "MODE: review" in fakes.calls[0]["prompt"]
    assert "MODE: auto" in fakes.calls[1]["prompt"]
    assert app("g:1")["status"] == "ready-to-submit"
    assert app("g:2")["status"] == "submitted"
    assert app("g:3")["status"] == "submitted"   # kept, picked up once the first review was done


def test_kept_postings_wait_for_review_first_and_review_mode(fakes):
    add_posting("g:1")
    assert apply_queue("r1").startswith("No approved postings")   # review mode: kept never auto-applied
    assert fakes.calls == []
    set_settings(mode="auto", review_first=5)
    assert apply_queue("r2").startswith("No approved postings")   # auto, but nothing reviewed yet


def test_daily_limit_and_explicit_limit(fakes):
    s = config.load_settings()
    s["queue"]["daily_limit"] = 2
    config.save_settings(s)
    for i in range(4):
        add_posting(f"g:{i}", first_seen_at=f"2026-01-0{i + 1}T00:00:00+00:00")
    approve(*[f"g:{i}" for i in range(4)])
    apply_queue("r1")
    assert len(fakes.calls) == 2
    assert "limit of 2" in apply_queue("r2")                    # used up for today
    assert len(fakes.calls) == 2
    s["queue"]["daily_limit"] = 10
    config.save_settings(s)
    apply_queue("r3", limit=1)
    assert len(fakes.calls) == 3


def test_skips_postings_already_applied_to_and_twins(fakes):
    add_posting("g:1", title="Software Intern")
    add_posting("l:1", source="lever", title="Software Intern")     # same role, other board
    approve("g:1", "l:1")
    apply_queue("r1")
    assert len(fakes.calls) == 1                                    # the twin is skipped
    assert apply_queue("r2").startswith("No approved postings")
    assert len(fakes.calls) == 1


def test_failed_postings_are_not_retried_automatically(fakes):
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("failed", notes="The posting is closed.")]
    apply_queue("r1")
    assert app("g:1")["status"] == "failed" and "closed" in app("g:1")["notes"]
    apply_queue("r2")
    assert len(fakes.calls) == 1


def test_queued_row_is_picked_up_without_a_second_row(fakes):
    add_posting("g:1")
    store.execute("INSERT INTO applications (posting_id, company, title, status, created_at, updated_at) "
                  "VALUES ('g:1','Acme','Software Intern','queued','2026-01-01','2026-01-01')")
    apply_queue("r1")
    assert store.one("SELECT COUNT(*) n FROM applications")["n"] == 1
    assert app("g:1")["status"] == "ready-to-submit"


def test_needs_you_question_flow_and_retry_after_answer(fakes):
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("needs-you", needs_you_reason="Two questions need answers.",
                            pending_questions=[
                                {"question": "Years of Rust?", "type": "select", "options": ["0", "1-2"]},
                                {"question": "Are you a Rust expert?", "type": "radio", "options": ["Yes", "No"]},
                            ])]
    apply_queue("r1")
    row = app("g:1")
    assert row["status"] == "needs-you" and row["needs_you"] == "Two questions need answers."
    pend = store.rows("SELECT * FROM answers WHERE pending=1")
    assert len(pend) == 2
    assert store.one("SELECT type, options FROM application_questions WHERE key='years of rust'") == {
        "type": "select", "options": '["0", "1-2"]'}

    apply_queue("r2")                         # still pending: not retried
    assert len(fakes.calls) == 1

    learn("Years of Rust?", "1-2")
    apply_queue("r3")                         # one answered, one still pending: still waiting
    assert len(fakes.calls) == 1

    learn("Are you a Rust expert?", "No")
    fakes.results = [result("ready-to-submit")]
    apply_queue("r4")                         # all answered: retried on the same row
    assert len(fakes.calls) == 2
    assert store.one("SELECT COUNT(*) n FROM applications")["n"] == 1
    assert app("g:1")["status"] == "ready-to-submit" and app("g:1")["needs_you"] == ""
    assert "Years of Rust? => 1-2" in fakes.calls[1]["prompt"]


def test_questions_force_needs_you_even_if_claude_says_ready(fakes):
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("ready-to-submit", pending_questions=[{"question": "Security clearance level?"}])]
    apply_queue("r1")
    row = app("g:1")
    assert row["status"] == "needs-you" and row["needs_you"]


def test_sign_in_wall_and_captcha_become_needs_you(fakes):
    add_posting("g:1", first_seen_at="2026-01-01T00:00:00+00:00")
    add_posting("g:2", title="Other Intern", first_seen_at="2026-02-01T00:00:00+00:00")
    approve("g:1", "g:2")
    fakes.results = [result("needs-you", needs_you_reason="sign-in needed: Acme"),
                     result("needs-you", needs_you_reason="CAPTCHA on Acme")]
    apply_queue("r1")
    assert app("g:1")["needs_you"] == "sign-in needed: Acme"
    assert app("g:2")["needs_you"] == "CAPTCHA on Acme"
    apply_queue("r2")                         # these wait for the person; no automatic retry
    assert len(fakes.calls) == 2


def test_cost_recorded_per_attempt_and_summed(fakes):
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("needs-you", cost=0.30, needs_you_reason="x", pending_questions=[{"question": "Q one?"}])]
    apply_queue("r1")
    learn("Q one?", "A")
    fakes.results = [result("ready-to-submit", cost=0.45)]
    apply_queue("r2")
    rows = store.rows("SELECT cost_usd, outcome_status, mode FROM application_costs ORDER BY id")
    assert [r["cost_usd"] for r in rows] == [0.30, 0.45]
    assert [r["outcome_status"] for r in rows] == ["needs-you", "ready-to-submit"]
    assert store.one("SELECT SUM(cost_usd) c FROM application_costs")["c"] == pytest.approx(0.75)


def test_answers_used_are_learned_and_counted(fakes):
    learn("Do you know SQL?", "Yes")
    add_posting("g:1")
    approve("g:1")
    fakes.results = [result("ready-to-submit", answers_used=[
        {"question": "Do you know SQL?", "answer": "Yes"},
        {"question": "Are you over 18?", "answer": "Yes"},
        {"question": "First name", "answer": "Alex"},
    ])]
    apply_queue("r1")
    assert "Do you know SQL? => Yes" in fakes.calls[0]["prompt"]
    assert store.one("SELECT uses FROM answers WHERE key='do you know sql'")["uses"] == 1
    assert store.one("SELECT answer, uses, source FROM answers WHERE key='are you over 18'") == {
        "answer": "Yes", "uses": 1, "source": "learned"}
    assert store.one("SELECT key FROM answers WHERE key='first name'") is None


def test_workday_posting_gets_the_script_in_its_brief(fakes):
    add_posting("w:1", ats="workday", url="https://acme.wd1.myworkdayjobs.com/en-US/x/job/1", apply_url="")
    approve("w:1")
    apply_queue("r1")
    assert "wdFill(ANSWERS)" in fakes.calls[0]["prompt"]


def test_claude_failure_is_recorded_loudly(fakes):
    add_posting("g:1")
    approve("g:1")
    fakes.results = [__import__("applyfirst.claude", fromlist=["Result"]).Result(False, error="Claude Code is not installed or not on PATH.")]
    summary = apply_queue("r1")
    row = app("g:1")
    assert row["status"] == "failed" and "not installed" in row["notes"]
    assert "1 failed" in summary
    assert store.one("SELECT COUNT(*) n FROM application_costs")["n"] == 1


def test_stops_after_three_failures_in_a_row(fakes):
    for i in range(5):
        add_posting(f"g:{i}", title=f"Role {i}", first_seen_at=f"2026-01-0{i + 1}T00:00:00+00:00")
    approve(*[f"g:{i}" for i in range(5)])
    fakes.results = [result("failed", notes="boom")] * 5
    apply_queue("r1")
    assert len(fakes.calls) == 3


def test_missing_resume_fails_the_row_without_calling_claude(fakes):
    fakes.resume.unlink()
    add_posting("g:1")
    approve("g:1")
    apply_queue("r1")
    assert fakes.calls == []
    assert app("g:1")["status"] == "failed" and "resume" in app("g:1")["notes"].lower()


def test_cover_letter_built_when_posting_mentions_one(fakes, tmp_path):
    letter = tmp_path / "letter.pdf"
    letter.write_bytes(b"x")
    fakes.resume_mod.cover_letter = lambda posting, run_id=None: str(letter)
    add_posting("g:1", description="Please attach a cover letter.",
                 first_seen_at="2026-01-01T00:00:00+00:00")
    add_posting("g:2", title="Other", description="No letter needed.", first_seen_at="2026-02-01T00:00:00+00:00")
    approve("g:1", "g:2")
    apply_queue("r1")
    assert str(letter) in fakes.calls[0]["prompt"]
    assert str(letter) not in fakes.calls[1]["prompt"]
    assert app("g:1")["cover_letter_file"] == "letter.pdf"


def test_missing_sibling_package_gives_a_clear_message(alex, monkeypatch):
    monkeypatch.setitem(sys.modules, "applyfirst.filters", types.ModuleType("applyfirst.filters"))
    with pytest.raises(RuntimeError, match="applyfirst.filters.queue"):
        apply_queue("r1")
    monkeypatch.setitem(sys.modules, "applyfirst.filters", None)    # import raises ImportError
    with pytest.raises(RuntimeError, match="not available"):
        apply_queue("r1")
