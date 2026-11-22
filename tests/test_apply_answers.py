from applyfirst import config, store
from applyfirst.apply import (
    learn, learned_answers, mark_pending, normalize_key, pending_for, record_used,
    salary_from_posting, standard_answers, workday_answers,
)
from applyfirst.apply.brief import STOCK_PHRASES, build_brief, is_workday
from test_apply_support import add_posting


def std(alex, posting=None, **apply):
    s = config.load_settings()
    s["apply"].update(apply)
    return standard_answers(alex, s, posting)


def test_standard_answers_from_profile(alex):
    a = std(alex)
    assert a["contact"]["full_name"] == "Alex Rivera"
    assert a["contact"]["country"] == "Canada"
    assert a["education"]["school"] == "Example University"
    assert a["education"]["graduation"]["my"] == "04/2028"
    assert a["work_authorization"]["CA"] == {"country": "Canada", "authorized": "Yes", "needs_sponsorship": "No"}
    assert a["work_authorization"]["US"]["authorized"] == "No"
    assert a["work_authorization"]["US"]["needs_sponsorship"] == "Yes"
    assert a["start_date"]["mdy"] == "05/01/2027"
    assert a["start_date"]["text"] == "May 2027"
    assert a["term_length"]["longest"] == 12
    assert a["languages"] == [{"language": "English", "level": "Native"}]


def test_demographics_empty_means_decline(alex):
    a = std(alex)
    assert set(a["demographics"].values()) == {""}
    assert "decline" in a["demographics_note"]


def test_salary_posting_minimum_beats_profile(alex):
    posting = add_posting(description="Compensation $24.50 - $32.00 per hour, CAD.")
    a = std(alex, posting)
    assert a["salary"]["amount"] == "24.5"
    assert a["salary"]["unit"] == "hour"
    assert a["salary"]["source"] == "posting range minimum"
    assert a["salary"]["currency"] == "CAD"


def test_salary_falls_back_to_profile_then_none(alex):
    posting = add_posting(description="No pay stated.")
    a = std(alex, posting)
    assert (a["salary"]["amount"], a["salary"]["source"]) == ("25", "profile")
    alex2 = {**alex, "salary": {"currency": "", "hourly_min": None, "annual_min": None}}
    assert standard_answers(alex2, config.load_settings(), posting)["salary"] is None


def test_salary_parsing_shapes():
    assert salary_from_posting({"description": "$70,000 - $90,000 per year"})["amount"] == "70000"
    assert salary_from_posting({"description": "Salary: $70K to $90K"})["amount"] == "70000"
    assert salary_from_posting({"description": "$30 - $40 per hour"})["unit"] == "hour"
    # a bonus or a team size is not a pay range
    assert salary_from_posting({"description": "Join our team of 5 to 10 engineers, $5,000 bonus"}) is None
    assert salary_from_posting({"description": ""}) is None


def test_work_authorization_for_posting_country(alex):
    us = add_posting("g:2", country="US")
    a = std(alex, us)
    assert a["work_authorization_for_this_posting"]["authorized"] == "No"
    de = add_posting("g:3", country="DE")
    assert std(alex, de)["work_authorization_for_this_posting"] is None


def test_future_commitments_yes_vs_literal(alex):
    yes = std(alex, future_commitments="yes")
    assert yes["commitments"]["willing_to_travel"] == "Yes"
    profile = {**alex, "availability": {**alex["availability"], "willing_to_relocate": False}}
    s = config.load_settings()
    s["apply"]["future_commitments"] = "literal"
    lit = standard_answers(profile, s)
    assert lit["commitments"] == {"policy": "literal", "willing_to_relocate": "No"}
    s["apply"]["future_commitments"] = "yes"
    assert standard_answers(profile, s)["commitments"]["willing_to_relocate"] == "Yes"


def test_how_did_you_hear_follows_source(alex):
    assert std(alex, add_posting("i:1", source="indeed"))["how_did_you_hear"] == "Indeed"
    assert std(alex, add_posting("i:2", source="greenhouse"))["how_did_you_hear"] == "Company website"


def test_workday_answers_shape(alex):
    posting = add_posting("w:1", country="US")
    w = workday_answers(std(alex, posting), posting)
    assert w["firstName"] == "Alex" and w["email"] == "alex.rivera@example.com"
    assert w["startDate"] == "05/01/2027"
    assert w["gradDate"] == "04/2028"
    assert w["workAuth"]["CA"] == {"authorized": "Yes", "sponsorship": "No"}
    assert w["workAuth"]["US"] == {"authorized": "No", "sponsorship": "Yes"}
    assert w["defaultCountry"] == "US"
    assert w["salary"] == "24"
    assert "demographics" in w


def test_learn_and_normalize(tmp_home):
    assert normalize_key("  Are you 18+ years old? *") == "are you 18 years old"
    assert learn("Do you have a driver's licence?", "Yes")
    assert not learn("Empty?", "  ")
    row = store.one("SELECT * FROM answers WHERE key=?", (normalize_key("Do you have a driver's licence?"),))
    assert row["answer"] == "Yes" and row["source"] == "user" and row["pending"] == 0
    learn("do you have a drivers licence", "No")  # same key after normalisation? apostrophe splits, so a new key
    assert len(learned_answers()) == 2


def test_learn_keeps_first_question_text_and_uses(tmp_home):
    learn("Favourite color?", "Blue")
    store.execute("UPDATE answers SET uses=3")
    learn("favourite color", "Green")
    row = store.one("SELECT * FROM answers")
    assert row["question"] == "Favourite color?"
    assert row["answer"] == "Green" and row["uses"] == 3


def test_pending_question_flow(tmp_home):
    store.execute("INSERT INTO applications (posting_id, company, title, created_at, updated_at) VALUES ('p','A','T','x','x')")
    assert mark_pending(1, "Years of Rust experience?", "select", ["0", "1-2", "3+"])
    row = store.one("SELECT * FROM answers")
    assert row["pending"] == 1 and row["answer"] == ""
    assert [q["question"] for q in pending_for(1)] == ["Years of Rust experience?"]
    assert learned_answers() == []  # pending never shown as an answer
    learn("Years of Rust experience?", "1-2")
    assert pending_for(1) == []


def test_mark_pending_false_when_already_answered(tmp_home):
    learn("Do you need a visa?", "No")
    assert mark_pending(1, "Do you need a visa?") is False
    assert store.one("SELECT pending FROM answers")["pending"] == 0


def test_record_used_learns_counts_and_skips(alex):
    learn("Do you know SQL?", "Yes")
    standard = std(alex)
    out = record_used([
        {"question": "Do you know SQL?", "answer": "Yes"},                       # reuse: uses+1
        {"question": "Are you over 18?", "answer": "Yes"},                       # new: learned
        {"question": "First name", "answer": "Alex"},                            # from the profile: not stored
        {"question": "Why do you want to work here?", "answer": "Because."},     # per-posting: not stored
        {"question": "Describe a project", "answer": "x" * 400},                 # too long: not stored
        {"question": "Blank", "answer": ""},
    ], standard)
    assert out == {"learned": 1, "reused": 1}
    assert store.one("SELECT uses FROM answers WHERE key='do you know sql'")["uses"] == 1
    assert store.one("SELECT source, uses FROM answers WHERE key='are you over 18'") == {"source": "learned", "uses": 1}
    assert store.one("SELECT key FROM answers WHERE key='first name'") is None


def test_record_used_never_overwrites_a_pending_question(tmp_home):
    mark_pending(1, "Mystery question")
    record_used([{"question": "Mystery question", "answer": "guess"}])
    row = store.one("SELECT * FROM answers")
    assert row["pending"] == 1 and row["answer"] == ""


def test_is_workday():
    assert is_workday({"url": "https://nvidia.wd5.myworkdayjobs.com/en-US/x/job/1"})
    assert is_workday({"url": "https://x.example.com", "ats": "workday"})
    assert not is_workday({"url": "https://boards.greenhouse.io/x/jobs/1", "apply_url": ""})


def brief(alex, posting, mode="review", **kw):
    s = config.load_settings()
    standard = standard_answers(alex, s, posting)
    args = dict(
        mode=mode, resume_path="C:/r/Alex_Rivera_Resume.pdf", cover_letter_path=None,
        cover_letters_setting="when-required", standard=standard,
        learned=[{"question": "Do you know SQL?", "answer": "Yes"}],
        experience=["Built a Chrome extension with 17 users"], settings_apply=s["apply"],
        browser="chrome-extension",
        workday=workday_answers(standard, posting) if is_workday(posting) else None,
    )
    args.update(kw)
    return build_brief(posting, **args)


def test_brief_review_mode_never_submits(alex):
    p = add_posting()
    b = brief(alex, p, "review")
    assert "MODE: review" in b and "Do not click the final" in b
    assert "ready-to-submit" in b
    assert "Alex_Rivera_Resume.pdf" in b
    assert "Do you know SQL? => Yes" in b
    assert "Built a Chrome extension with 17 users" in b
    assert "READ EVERYTHING BACK" in b
    assert "CAPTCHA" in b and "sign-in" in b.lower()
    assert "pending_questions" in b
    assert "WORKDAY" not in b


def test_brief_auto_mode_submits_and_copies_confirmation(alex):
    b = brief(alex, add_posting(), "auto")
    assert "MODE: auto" in b and "confirmation_text" in b
    assert "Do not click the final" not in b


def test_brief_closes_tabs_the_person_does_not_need(alex):
    # Sign-in walls and pending questions are retried in a new tab, so a kept tab is a duplicate.
    for mode in ("auto", "review"):
        b = brief(alex, add_posting(f"t:{mode}"), mode)
        assert "keep the form tab open ONLY when" in b
        assert "Close the\n  tab, then report needs-you" in b
        assert "close the tab before you report" in b


def test_brief_workday_injects_script(alex):
    p = add_posting("w:1", ats="workday", url="https://acme.wd1.myworkdayjobs.com/x/job/1")
    b = brief(alex, p)
    assert "workday_fill.js" in b and "wdFill(ANSWERS)" in b and "javascript_tool" in b
    assert '"firstName": "Alex"' in b
    pw = brief(alex, p, browser="playwright")
    assert "browser_evaluate" in pw


def test_brief_has_no_em_dashes_and_lists_stock_phrases(alex):
    b = brief(alex, add_posting())
    assert "\u2014" not in b
    assert all(phrase in b for phrase in STOCK_PHRASES[:5])


def test_brief_cover_letter_variants(alex):
    p = add_posting()
    assert "cover letter required" in brief(alex, p)
    assert "leave optional cover letter fields empty" in brief(alex, p, cover_letters_setting="never")
    assert "C:/r/letter.pdf" in brief(alex, p, cover_letter_path="C:/r/letter.pdf")
