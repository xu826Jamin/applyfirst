"""Cases seen in a live Ontario software search that should not have been kept."""
from applyfirst import config
from applyfirst.filters import evaluate
from applyfirst.filters.places import check_location

ONTARIO = {"countries": ["CA"], "regions": ["Ontario"], "cities": [], "remote": "include"}


def test_us_only_remote_is_outside_canada():
    res = check_location({"location": "Remote (Any State)", "remote": 1}, ONTARIO)
    assert not res.ok and res.code == "country"
    assert check_location({"location": "Remote", "remote": 1}, ONTARIO).ok


def test_posting_with_text_but_no_sign_of_the_field_is_skipped(alex):
    s = config.load_settings()
    s["search"]["fields"] = ["software"]
    insurance = ("Join our claims team for the summer. You will review policy files, speak with "
                 "policyholders, document claim notes, and support adjusters through the season. "
                 "Strong written communication and attention to detail are required. ") * 2
    verdict, reasons = evaluate({"id": "x", "title": "Claims Summer Student", "company": "Acme",
                                 "location": "Toronto, ON", "description": insurance,
                                 "first_seen_at": "2026-11-15T00:00:00+00:00"}, s, alex)
    assert verdict == "skip", reasons
    # no text at all: no evidence either way, still kept
    verdict, _ = evaluate({"id": "y", "title": "Summer Student", "company": "Acme",
                           "location": "Toronto, ON", "description": "",
                           "first_seen_at": "2026-11-15T00:00:00+00:00"}, s, alex)
    assert verdict == "keep"
