"""tracker.stats(): honest numbers, with sample sizes, and no chasing noise."""
from __future__ import annotations

from applyfirst import tracker
from applyfirst.tracker import insights

from test_tracker_helpers import add_app, add_posting


def seed(n: int, interviews: int, *, source="greenhouse", field="software", level="internship",
         resume="Alex_Rivera_Resume.pdf", seen="2026-11-01T09:00:00+00:00",
         submitted="2026-11-01T12:00:00+00:00", tag="x", rejects=0):
    """n submitted applications of one kind, `interviews` of them with an interview outcome."""
    for i in range(n):
        pid = add_posting(f"{tag}-{i}", f"Co{tag}{i}", "Role", source=source, field=field,
                          level=level, first_seen=seen)
        outcome = "interview" if i < interviews else ("rejected" if i < interviews + rejects else "")
        add_app(f"Co{tag}{i}", "Role", posting_id=pid, submitted_at=submitted, outcome=outcome,
                resume_file=resume)


def group(rows, name):
    return next(g for g in rows if g["group"] == name)


def test_empty_database_gives_zeros_not_errors(tmp_home):
    s = tracker.stats()
    assert s["applications"] == 0 and s["interviews"] == 0 and s["interview_rate"] is None
    assert s["weekly"] == [] and s["by_source"] == []


def test_totals_count_only_applications_that_went_in(tmp_home):
    seed(10, 2, rejects=3, tag="a")
    add_app("Queued Co", "Role", status="queued")
    add_app("Failed Co", "Role", status="failed")
    add_app("Ready Co", "Role", status="ready-to-submit")
    s = tracker.stats()
    t = s["totals"]
    assert s["applications"] == 10 and t["sample_size"] == 10
    assert s["interviews"] == 2 and s["responses"] == 5       # rejections are responses
    assert s["interview_rate"] == 0.2 and t["response_rate"] == 0.5
    assert s["waiting_for_you"] == 1


def test_assessment_interview_and_offer_all_count_as_interviews(tmp_home):
    for o in ("assessment", "interview", "offer", "rejected", "withdrawn", ""):
        add_app(f"Co {o}", "Role", outcome=o)
    s = tracker.stats()
    assert s["applications"] == 6 and s["interviews"] == 3 and s["responses"] == 4


def test_an_outcome_proves_it_was_submitted_even_if_status_lags(tmp_home):
    add_app("Odd Co", "Role", status="ready-to-submit", outcome="interview")
    assert tracker.stats()["applications"] == 1


def test_small_groups_are_marked_too_few_and_five_positives_unlock_a_comparison(tmp_home):
    seed(20, 5, source="greenhouse", tag="g")        # 5 interviews: enough
    seed(20, 4, source="lever", tag="l")             # 4 interviews: too few
    s = tracker.stats()
    g, l = group(s["by_source"], "greenhouse"), group(s["by_source"], "lever")
    assert g["enough_data"] and g["note"] == ""
    assert not l["enough_data"] and l["note"] == "too few to compare"
    for grp in (g, l):
        assert grp["sample_size"] == 20 and grp["applications"] == 20
    assert g["interview_rate"] == 0.25 and l["interview_rate"] == 0.2
    # totals are labelled too
    assert s["totals"]["enough_data"] and s["totals"]["sample_size"] == 40


def test_every_rate_carries_a_sample_size_in_every_breakdown(tmp_home):
    seed(6, 1, tag="a")
    seed(6, 0, source="lever", field="hardware", level="co-op", tag="b")
    s = tracker.stats()
    for key in ("by_source", "by_resume", "by_field", "by_level", "by_posting_age"):
        assert s[key], key
        for g in s[key]:
            assert g["sample_size"] == g["applications"] > 0
            assert "interview_rate" in g and "enough_data" in g and "note" in g
    assert s["totals"]["note"] == "too few to compare"


def test_breakdowns_by_source_resume_field_level(tmp_home):
    seed(4, 1, source="greenhouse", field="software", level="internship",
         resume="/data/resumes/Alex_Rivera_Resume.pdf", tag="a")
    seed(3, 0, source="lever", field="hardware", level="co-op",
         resume="Alex_Rivera_Acme_Resume.pdf", tag="b")
    add_app("Manual Co", "Role")        # no posting, no resume recorded
    s = tracker.stats()
    assert group(s["by_source"], "greenhouse")["applications"] == 4
    assert group(s["by_source"], "unknown")["applications"] == 1
    assert group(s["by_resume"], "Alex_Rivera_Resume.pdf")["interviews"] == 1   # file name only
    assert group(s["by_resume"], "not recorded")["applications"] == 1
    assert group(s["by_field"], "hardware")["applications"] == 3
    assert group(s["by_level"], "co-op")["applications"] == 3


def test_posting_age_buckets(tmp_home):
    cases = {
        "under 24 hours": "2026-11-01T20:00:00+00:00",     # 11 h
        "1 to 3 days": "2026-11-03T09:00:00+00:00",        # 48 h
        "4 to 7 days": "2026-11-06T09:00:00+00:00",        # 120 h
        "older than a week": "2026-11-20T09:00:00+00:00",  # 19 days
    }
    for name, submitted in cases.items():
        seed(1, 0, submitted=submitted, tag=name[:3])
    add_app("No Posting Co", "Role", submitted_at="2026-11-04T09:00:00+00:00")   # age unknown
    s = tracker.stats()
    names = [g["group"] for g in s["by_posting_age"]]
    assert names == ["under 24 hours", "1 to 3 days", "4 to 7 days", "older than a week", "unknown"]
    assert all(g["applications"] == 1 for g in s["by_posting_age"])


def test_age_bucket_edges():
    b = insights.age_bucket
    assert b(0) == "under 24 hours" and b(23.9) == "under 24 hours"
    assert b(24) == "1 to 3 days" and b(95.9) == "1 to 3 days"
    assert b(96) == "4 to 7 days" and b(191.9) == "4 to 7 days"
    assert b(192) == "older than a week" and b(None) == "unknown"
    assert insights.age_hours("2026-11-01T09:00:00+00:00", "2026-11-02T09:00:00Z") == 24
    assert insights.age_hours("2026-11-02T09:00:00+00:00", "2026-11-01T09:00:00+00:00") == 0  # clamped
    assert insights.age_hours("", "2026-11-01T09:00:00+00:00") is None


def test_weekly_series_groups_by_week_of_submission(tmp_home):
    seed(2, 1, submitted="2026-11-02T10:00:00+00:00", tag="w1")      # Monday 2 Nov
    seed(3, 0, submitted="2026-11-08T23:00:00+00:00", tag="w2")      # Sunday, same week
    seed(1, 1, submitted="2026-11-10T10:00:00+00:00", tag="w3")      # next week
    w = tracker.stats()["weekly"]
    assert [x["week_start"] for x in w] == ["2026-11-02", "2026-11-09"]
    assert (w[0]["applications"], w[0]["interviews"]) == (5, 1)
    assert (w[1]["applications"], w[1]["interviews"]) == (1, 1)
    assert all("sample_size" in x and "note" in x for x in w)


def test_insights_only_compare_groups_with_enough_interviews(tmp_home):
    seed(10, 6, source="greenhouse", tag="g")
    seed(20, 5, source="lever", tag="l")
    seed(5, 1, source="ashby", tag="a")      # too few: must not appear in a sentence
    s = tracker.stats()
    texts = [t for t in s["insights"] if t.startswith("Source")]
    assert texts and "greenhouse" in texts[0] and "lever" in texts[0]
    assert "ashby" not in texts[0] and "6 of 10" in texts[0]


def test_no_insight_when_nothing_is_comparable(tmp_home):
    seed(10, 3, source="greenhouse", tag="g")
    seed(10, 2, source="lever", tag="l")
    assert tracker.stats()["insights"] == []
