"""tracker: classification, matching, and the read-only IMAP sync. All offline, all fictional."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from applyfirst import config, store, tracker
from applyfirst.tracker import classifier, imapmail, matcher, record, syncer

import test_tracker_helpers as H
from test_tracker_helpers import StubIMAP, add_app, add_posting, app, raw_mail


# --------------------------------------------------------------------------- classify

@pytest.mark.parametrize("subject,body,sender,expected", [
    ("Your application to Brightwave", "Thank you for applying to the Software Intern role. "
     "Your application has been received.", "no-reply@greenhouse.io", "confirmation"),
    ("Update on your application", "Hello Alex, unfortunately we will not be moving forward "
     "with your application.", "jobs@brightwave.example", "rejection"),
    ("Thank you for your interest in Brightwave", "Thank you again for your interest. We have "
     "decided to proceed with other candidates.", "no-reply@lever.co", "rejection"),
    ("Brightwave online assessment", "Please complete the coding challenge on HackerRank "
     "within 5 days.", "jobs@brightwave.example", "assessment"),
    ("Interview with Brightwave", "We would like to schedule an interview with you.",
     "recruiting@brightwave.example", "interview"),
    ("Next steps", "We are excited to advance you to the final round.", "hr@brightwave.example",
     "interview"),
    ("Offer from Brightwave", "We are pleased to offer you the Software Intern position. "
     "Your offer letter is attached.", "hr@brightwave.example", "offer"),
    ("Role update", "We have filled the Software Intern role and are no longer accepting "
     "applications.", "no-reply@ashbyhq.com", "rejection"),
    ("Brightwave update", "Thank you for your interest in the opportunity with Brightwave and "
     "for taking the time to submit an application. We have", "no-reply@ashbyhq.com", "other"),
    ("Weekly tips", "Ten ways to get a recruiter's attention", "tips@careerdaily.example",
     "other"),
])
def test_classify(subject, body, sender, expected):
    assert tracker.classify(subject, body, sender) == expected


def test_a_verdict_beats_thanks_for_your_interest_and_an_interview_beats_a_confirmation():
    assert tracker.classify(
        "Thank you for your interest", "Thank you for applying. Unfortunately we will not be "
        "moving forward.", "x@lever.co") == "rejection"
    assert tracker.classify(
        "Thanks for applying", "Thank you for applying. We would like to schedule an interview.",
        "x@lever.co") == "interview"


def test_newsletters_never_classify_as_replies():
    for sender in ("dan@tldrnewsletter.com", "digest@careerdaily.example",
                   "jobalerts-noreply@linkedin.com", "donotreply@match.indeed.com"):
        assert tracker.classify("Interview: online assessment tips for your internship",
                                "Unfortunately the assessment is hard.", sender) == "other"


def test_classes_are_the_contract_set():
    assert set(tracker.CLASSES) == {"confirmation", "rejection", "assessment", "interview",
                                    "offer", "other"}


# --------------------------------------------------------------------------- matching

def msg(frm, subject, body, date="2026-11-10T12:00:00+00:00", mid="m1", thread=None):
    return {"id": mid, "thread_id": thread or mid, "from": frm, "subject": subject,
            "body": body, "date": date}


def pool(learned=None):
    return matcher.Pool(matcher.load_pool(), learned)


def test_single_application_is_matched_by_employer(tmp_home):
    a = add_app("Brightwave Inc.", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    add_app("Kestrel Robotics", "Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    res, _ = matcher.analyze([msg("jobs@brightwave.example", "Brightwave application update",
                                  "Unfortunately we will not be moving forward with your "
                                  "application for the internship.")], pool())
    assert res[0]["class"] == "rejection" and res[0]["app_ids"] == [a]


def test_two_applications_one_employer_are_split_by_role_words(tmp_home):
    a = add_app("Brightwave", "Embedded Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    b = add_app("Brightwave", "Data Analyst Intern", submitted_at="2026-11-02T10:00:00+00:00")
    res, _ = matcher.analyze([msg("no-reply@greenhouse.io", "Brightwave: Data Analyst Intern",
                                  "Hello Alex, we received your application for the Data Analyst "
                                  "role at Brightwave.")], pool())
    assert res[0]["app_ids"] == [b] and a not in res[0]["app_ids"]


def test_exact_title_with_a_parenthetical_wins_over_the_plain_posting(tmp_home):
    plain = add_app("Brightwave", "Fraud Analyst Intern", submitted_at="2026-11-02T10:00:00+00:00",
                    posting_id="p-plain")
    earn = add_app("Brightwave", "Fraud Analyst Intern (Earnings)",
                   submitted_at="2026-11-02T10:00:00+00:00", posting_id="p-earn")
    res, _ = matcher.analyze([msg("no-reply@ashbyhq.com", "Your application to Brightwave",
                                  "Unfortunately we will not be moving forward with your "
                                  "application for the Fraud Analyst Intern (Earnings) role at "
                                  "Brightwave.")], pool())
    assert res[0]["app_ids"] == [earn] and plain not in res[0]["app_ids"]


def test_ambiguous_mail_is_left_unmatched_with_its_candidates(tmp_home):
    a = add_app("Brightwave", "Embedded Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    b = add_app("Brightwave", "Data Analyst Intern", submitted_at="2026-11-02T10:00:00+00:00")
    res, _ = matcher.analyze([msg("no-reply@greenhouse.io", "Brightwave: your application",
                                  "Unfortunately we are not moving forward with your "
                                  "application.")], pool())
    r = res[0]
    assert r["class"] == "rejection" and r["app_ids"] == [] and r["ambiguous"]
    assert set(r["candidates"]) == {a, b}


def test_identical_duplicate_applications_count_once(tmp_home):
    a = add_app("Brightwave", "Software Intern", posting_id="p1",
                submitted_at="2026-11-02T10:00:00+00:00")
    b = add_app("Brightwave", "Software Intern", posting_id="p1",
                submitted_at="2026-11-02T11:00:00+00:00")
    pl = pool()
    mt = matcher.match(msg("jobs@brightwave.example", "Brightwave interview",
                           "Interview for the Software Intern role at Brightwave."),
                       "interview", pl)
    # one application only, never both
    assert mt["app_ids"] == [min(a, b)]


def test_a_reply_dated_before_the_application_is_not_applied(tmp_home):
    add_app("Brightwave", "Software Intern", submitted_at="2026-11-10T10:00:00+00:00")
    res, _ = matcher.analyze([msg("jobs@brightwave.example", "Brightwave application",
                                  "Unfortunately we will not be moving forward with your "
                                  "internship application.", date="2026-10-01T10:00:00+00:00")],
                             pool())
    assert res[0]["app_ids"] == []


def test_employer_that_is_only_a_common_word_in_the_body_is_not_matched(tmp_home):
    add_app("Zip", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    res, _ = matcher.analyze([msg("no-reply@greenhouse.io", "Your application",
                                  "Please zip up your portfolio. Unfortunately we are not "
                                  "moving forward with your application.")], pool())
    assert res[0]["app_ids"] == []


def test_requisition_id_in_the_users_alias_file(tmp_home):
    a = add_app("Brightwave", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    add_app("Brightwave", "Data Intern", submitted_at="2026-11-02T10:00:00+00:00")
    (tmp_home / "tracker_aliases.json").write_text(json.dumps({"ids": {"r0098765": [a]}}))
    res, _ = matcher.analyze([msg("no-reply@greenhouse.io", "Action needed (R0098765)",
                                  "Hello Alex, a pending task for your online assessment "
                                  "awaits. Your application at Brightwave.")], pool())
    assert res[0]["app_ids"] == [a] and res[0]["class"] == "assessment"


def test_user_company_alias_is_honoured(tmp_home):
    a = add_app("Tern Analytics", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    (tmp_home / "tracker_aliases.json").write_text(
        json.dumps({"companies": {"tern": ["arctic-tern"]}}))
    res, _ = matcher.analyze([msg("hr@arctic-tern.example", "Arctic-Tern internship application",
                                  "Unfortunately we will not be moving forward with your "
                                  "internship application.")], pool())
    assert res[0]["app_ids"] == [a]


def test_an_anonymous_confirmation_is_placed_through_a_learned_sender_domain(tmp_home):
    a = add_app("Brightwave", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    res, new = matcher.analyze([
        msg("jobs@mail.brightwave-careers.example", "Brightwave internship application",
            "We have received your application for the internship at Brightwave.", mid="named"),
        msg("jobs@mail.brightwave-careers.example", "Thank you for applying!",
            "Thank you for applying. Your application has been received.", mid="anon"),
    ], pool())
    by = {r["msg"]["id"]: r for r in res}
    assert by["anon"]["app_ids"] == [a] and by["anon"]["class"] == "confirmation"
    assert "mail.brightwave-careers.example" in new


def test_unplaced_mail_takes_the_placement_of_its_thread(tmp_home):
    a = add_app("Brightwave", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    res, _ = matcher.analyze([
        msg("jobs@brightwave.example", "Brightwave interview", "Interview for the internship.",
            mid="x1", thread="t1"),
        msg("noreply@calendar.example", "Invitation: interview", "Interview: join the call. "
            "Application at your candidate portal.", mid="x2", thread="t1"),
    ], pool())
    # the second has no employer of its own and is not application mail unless inherited,
    # which it is not (untrusted): it must not be guessed
    by = {r["msg"]["id"]: r for r in res}
    assert by["x1"]["app_ids"] == [a]
    assert by["x2"]["app_ids"] == [] and not by["x2"]["trusted"]


def test_mail_from_unknown_sender_mentioning_an_employer_is_ignored(tmp_home):
    add_app("Brightwave", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    res, _ = matcher.analyze([msg("hello@careertips.example", "Your next interview",
                                  "How to prepare for your next interview at companies like "
                                  "Brightwave.")], pool())
    assert not res[0]["trusted"] and res[0]["class"] == "other"


# --------------------------------------------------------------------------- outcomes

def test_outcomes_only_move_forward(tmp_home):
    a = add_app("Brightwave", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    record.apply_class(a, "interview", "2026-11-08T10:00:00+00:00")
    assert app(a)["outcome"] == "interview"
    record.apply_class(a, "confirmation", "2026-11-09T10:00:00+00:00")   # generic thanks
    record.apply_class(a, "rejection", "2026-11-12T10:00:00+00:00")
    record.apply_class(a, "assessment", "2026-11-12T10:00:00+00:00")
    row = app(a)
    assert row["outcome"] == "interview" and row["outcome_at"].startswith("2026-11-08")
    record.apply_class(a, "offer", "2026-11-14T10:00:00+00:00")
    assert app(a)["outcome"] == "offer" and app(a)["outcome_source"] == "email"


def test_confirmation_marks_submitted_only_from_ready_or_filling(tmp_home):
    ready = add_app("A", "x", status="ready-to-submit")
    fill = add_app("B", "x", status="filling")
    failed = add_app("C", "x", status="failed")
    for i in (ready, fill, failed):
        record.apply_class(i, "confirmation", "2026-11-09T10:00:00+00:00")
    assert app(ready)["status"] == "submitted" and app(ready)["submitted_at"].startswith("2026-11-09")
    assert app(fill)["status"] == "submitted"
    assert app(failed)["status"] == "failed"
    assert app(ready)["outcome"] == ""      # a confirmation is never an outcome


def test_withdrawn_is_not_overridden_by_mail(tmp_home):
    a = add_app("Brightwave", "Software Intern", outcome="withdrawn")
    record.apply_class(a, "interview", "2026-11-09T10:00:00+00:00")
    assert app(a)["outcome"] == "withdrawn"


def test_manual_outcome_sets_any_value_and_marks_submitted(tmp_home):
    a = add_app("Brightwave", "Software Intern", status="ready-to-submit")
    row = record.set_manual_outcome(a, "interview")
    assert row["outcome"] == "interview" and row["outcome_source"] == "manual"
    assert row["status"] == "submitted"
    assert record.set_manual_outcome(a, "rejected")["outcome"] == "rejected"   # by hand, any order
    assert record.set_manual_outcome(a, "")["outcome"] == ""
    with pytest.raises(ValueError):
        record.set_manual_outcome(a, "hired!!")
    with pytest.raises(LookupError):
        record.set_manual_outcome(999, "interview")


# --------------------------------------------------------------------------- IMAP sync

@pytest.fixture
def mailbox(tmp_home, monkeypatch):
    """Configured mail plus a stub server; returns a function that sets what it holds."""
    H.configure_mail()
    StubIMAP.instances.clear()
    held: dict = {"msgs": []}

    def fake_connect(host, port, user, password):
        assert (host, user, password) == ("imap.example.test", "alex.rivera@example.com", "pw")
        return StubIMAP(held["msgs"])

    monkeypatch.setattr(imapmail, "connect", fake_connect)
    return held


def run_sync() -> str:
    rid = store.start_run("sync")
    out = tracker.sync(rid)
    store.finish_run(rid, out)
    return out


def test_sync_without_email_says_so_and_returns(tmp_home):
    out = run_sync()
    assert "not set up" in out.lower() and "by hand" in out
    assert "—" not in out
    assert store.rows("SELECT * FROM tracker_messages") == []


def test_sync_enabled_without_a_password_says_so(tmp_home):
    s = config.load_settings()
    s["tracker"]["email"].update({"enabled": True, "imap_host": "h", "username": "u"})
    config.save_settings(s)
    assert "password" in run_sync().lower()


def test_sync_reads_places_and_records(mailbox):
    a = add_app("Brightwave", "Software Intern", status="ready-to-submit")
    b = add_app("Kestrel Robotics", "Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    c = add_app("Hexwave Labs", "Test Intern", submitted_at="2026-11-02T10:00:00+00:00")
    mailbox["msgs"] = [
        raw_mail("no-reply@greenhouse.io", "Your application to Brightwave",
                 "Thank you for applying to the Software Intern role at Brightwave. Your "
                 "application has been received.", "2026-11-05T14:00:00", "conf1"),
        raw_mail("jobs@kestrel.example", "Kestrel Robotics: interview",
                 "We would like to schedule an interview for the Firmware Intern role at "
                 "Kestrel Robotics. SECRET-BODY-TEXT", "2026-11-09T14:00:00", "int1"),
        raw_mail("no-reply@lever.co", "Thank you for your interest in Hexwave Labs",
                 "Unfortunately we will not be moving forward with your Test Intern "
                 "application at Hexwave Labs.", "2026-11-10T14:00:00", "rej1"),
        raw_mail("dan@tldrnewsletter.com", "Interview tips and assessment hacks",
                 "Unfortunately the assessment is hard.", "2026-11-10T15:00:00", "news1"),
    ]
    out = run_sync()
    assert app(a)["status"] == "submitted" and app(a)["submitted_at"].startswith("2026-11-05")
    assert app(b)["outcome"] == "interview" and app(b)["outcome_source"] == "email"
    assert app(b)["outcome_at"].startswith("2026-11-09")
    assert app(c)["outcome"] == "rejected"
    assert "1 confirmations" in out and "1 interviews" in out
    msgs = store.rows("SELECT * FROM tracker_messages ORDER BY id")
    assert {m["class"] for m in msgs} == {"confirmation", "interview", "rejection"}
    assert all(m["application_id"] for m in msgs)
    assert not any("news1" in m["message_id"] for m in msgs)     # the newsletter is not kept
    # the body is never stored, anywhere in the database
    dump = json.dumps([dict(r) for r in store.db().execute("SELECT * FROM tracker_messages")])
    assert "SECRET-BODY-TEXT" not in dump


def test_sync_never_writes_to_the_mailbox(mailbox):
    add_app("Brightwave", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    mailbox["msgs"] = [raw_mail("jobs@brightwave.example", "Brightwave interview",
                                "We would like to schedule an interview for the internship.",
                                "2026-11-09T14:00:00", "i1")]
    run_sync()
    srv = StubIMAP.instances[-1]
    selects = [c for c in srv.calls if c[0] == "select"]
    assert selects and all(c[1] == "INBOX" and c[2] is True for c in selects)
    assert srv.logged_out
    cmds = {c[1] for c in srv.calls if c[0] == "uid"}
    assert cmds == {"SEARCH", "FETCH"}
    fetches = [c for c in srv.calls if c[0] == "uid" and c[1] == "FETCH"]
    assert all("BODY.PEEK" in c[3] for c in fetches)       # PEEK: nothing is marked seen


def test_the_stub_really_does_fail_on_a_write(mailbox):
    """The guard above is only worth something if it can fail: prove it does."""
    srv = StubIMAP([])
    with pytest.raises(AssertionError):
        srv.uid("STORE", "1", "+FLAGS", "\\Seen")


def test_first_run_reads_35_days_then_since_the_last_sync(mailbox):
    add_app("Brightwave", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    run_sync()
    first = [c for c in StubIMAP.instances[-1].calls if c[:2] == ("uid", "SEARCH")]
    want = imapmail.imap_date((datetime.now(timezone.utc) - timedelta(days=35)).date())
    assert all(c[3] == "SINCE" and c[4] == want for c in first)
    stamp = store.one("SELECT value FROM tracker_state WHERE key='last_sync_at'")["value"]
    assert stamp
    # pretend the last sync was ten days ago
    ten = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    store.upsert("tracker_state", {"key": "last_sync_at", "value": ten}, key="key")
    run_sync()
    later = [c for c in StubIMAP.instances[-1].calls if c[:2] == ("uid", "SEARCH")]
    want2 = imapmail.imap_date((datetime.now(timezone.utc) - timedelta(days=11)).date())
    assert all(c[4] == want2 for c in later)


def test_a_failed_sync_does_not_advance_the_high_water_mark(mailbox, monkeypatch):
    def boom(*a, **k):
        raise OSError("connection reset")
    monkeypatch.setattr(imapmail, "connect", boom)
    with pytest.raises(RuntimeError, match="sign in"):
        run_sync()
    assert store.one("SELECT * FROM tracker_state WHERE key='last_sync_at'") is None


def test_sync_twice_changes_nothing_the_second_time(mailbox):
    b = add_app("Kestrel Robotics", "Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    mailbox["msgs"] = [raw_mail("jobs@kestrel.example", "Kestrel Robotics: interview",
                                "We would like to schedule an interview for the Firmware "
                                "Intern role at Kestrel Robotics.", "2026-11-09T14:00:00", "i1")]
    run_sync()
    first = (app(b), store.rows("SELECT * FROM tracker_messages"))
    out = run_sync()
    assert (app(b), store.rows("SELECT * FROM tracker_messages")) == first
    assert out.startswith("Read 0 new emails")


def test_a_later_thanks_for_applying_does_not_overwrite_an_interview(mailbox):
    b = add_app("Kestrel Robotics", "Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    mailbox["msgs"] = [
        raw_mail("jobs@kestrel.example", "Kestrel Robotics: interview",
                 "We would like to schedule an interview for the Firmware Intern role at "
                 "Kestrel Robotics.", "2026-11-09T14:00:00", "i1"),
        raw_mail("jobs@kestrel.example", "Kestrel Robotics: thank you for applying",
                 "Thank you for applying to Kestrel Robotics. Your application has been "
                 "received.", "2026-11-11T14:00:00", "late-thanks"),
    ]
    run_sync()
    assert app(b)["outcome"] == "interview"


def test_ambiguous_mail_is_listed_as_unmatched_and_the_user_can_place_it(mailbox):
    a = add_app("Brightwave", "Embedded Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    b = add_app("Brightwave", "Data Analyst Intern", submitted_at="2026-11-02T10:00:00+00:00")
    mailbox["msgs"] = [raw_mail("jobs@brightwave-hr.example", "Brightwave: your application",
                                "Unfortunately we are not moving forward with your "
                                "application at Brightwave.", "2026-11-09T14:00:00", "amb1")]
    out = run_sync()
    assert "need you" in out
    unm = record.list_messages(unmatched=True)
    assert len(unm) == 1 and unm[0]["application_id"] is None
    assert {c["id"] for c in unm[0]["candidates"]} == {a, b}
    assert app(a)["outcome"] == "" and app(b)["outcome"] == ""        # nothing guessed
    res = record.match_message(unm[0]["id"], b)
    assert app(b)["outcome"] == "rejected" and app(a)["outcome"] == ""
    assert record.list_messages(unmatched=True) == []
    assert res["message"]["application_id"] == b
    # the sender domain is learned for this employer
    assert store.one("SELECT company_key FROM tracker_domains WHERE domain='brightwave-hr.example'")


def test_unmatched_when_no_application_exists_for_the_employer(mailbox):
    add_app("Brightwave", "Software Intern", submitted_at="2026-11-02T10:00:00+00:00")
    mailbox["msgs"] = [raw_mail("no-reply@greenhouse.io", "Thank you for applying",
                                "Thank you for applying. Your application has been received.",
                                "2026-11-09T14:00:00", "anon1")]
    run_sync()
    unm = record.list_messages(unmatched=True)
    assert len(unm) == 1 and unm[0]["class"] == "confirmation"


def test_mail_the_user_sent_is_never_read_as_a_reply(mailbox):
    b = add_app("Kestrel Robotics", "Firmware Intern", submitted_at="2026-11-02T10:00:00+00:00")
    mailbox["msgs"] = [raw_mail("alex.rivera@example.com", "Kestrel Robotics interview",
                                "Unfortunately I would like to schedule an interview for the "
                                "internship at Kestrel Robotics.", "2026-11-09T14:00:00", "me1")]
    run_sync()
    assert app(b)["outcome"] == "" and store.rows("SELECT * FROM tracker_messages") == []


def test_search_criteria_are_search_keys_only():
    from datetime import date
    searches = imapmail.build_searches(date(2026, 10, 11))
    assert searches and all(s[:2] == ["SINCE", "11-Oct-2026"] for s in searches)
    flat = " ".join(" ".join(s) for s in searches)
    assert "unfortunately" in flat and "SUBJECT" in flat and "TEXT" in flat
    for word in ("STORE", "FLAGS", "SEEN", "DELETE", "MOVE", "COPY"):
        assert word not in flat.upper().replace("DELETED", "")  # no state-changing key words
    # terms with a space are quoted as one IMAP string
    assert '"next steps"' in flat


def test_parse_message_handles_html_only_and_truncated_mail():
    html_mail = (b"From: HR <hr@brightwave.example>\r\nSubject: =?utf-8?q?Interview_=E2=80=93_Brightwave?=\r\n"
                 b"Date: Mon, 09 Nov 2026 14:00:00 +0000\r\nMessage-ID: <h1@example.test>\r\n"
                 b"Content-Type: text/html; charset=utf-8\r\n\r\n"
                 b"<html><style>p{}</style><body><p>We would like to <b>schedule</b> an "
                 b"interview.</p></body></html>")
    m = imapmail.parse_message(html_mail)
    assert m["id"] == "h1@example.test" and m["date"].startswith("2026-11-09T14:00")
    assert "schedule an interview" in m["body"].replace("  ", " ")
    assert "<" not in m["body"] and "p{}" not in m["body"]
    cut = (b"From: a@b.example\r\nSubject: s\r\nContent-Type: multipart/mixed; boundary=XX\r\n"
           b"\r\n--XX\r\nContent-Type: text/plain\r\n\r\nUnfortunately we will not")
    m2 = imapmail.parse_message(cut)
    assert m2 and "Unfortunately" in m2["body"]
