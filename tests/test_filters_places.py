"""Filters: the location check."""
import pytest

from applyfirst.filters import places as P

CA_ON = {"countries": ["CA"], "regions": ["Ontario"], "remote": "include"}


def check(location, search=None, **extra):
    return P.check_location({"location": location, **extra}, search or CA_ON)


@pytest.mark.parametrize("loc", [
    "Toronto, ON", "Toronto, Ontario, Canada", "Waterloo", "Hybrid - Toronto",
    "Toronto, Canada",              # a known city, country only
    "Mississauga, Ontario, Canada", "Kitchener-Waterloo", "Greater Toronto Area",
    "London, UK; Ontario, CAN",     # any one office that fits is enough
    "Remote",
    "",                             # unknown passes: silence is not a mismatch
])
def test_fits(loc):
    assert check(loc).ok


@pytest.mark.parametrize("loc,reason", [
    ("Calgary, AB", "Outside your locations: Calgary, AB"),
    ("Vancouver, BC", "Outside your locations: Vancouver, BC"),
    ("CA-QC-LONGUEUIL-J01 ~ 1000", "Outside your locations"),
    ("San Francisco, CA", "Outside your countries"),
    ("Vancouver, WA", "Outside your countries"),          # Washington, not British Columbia
    ("Remote - US", "Outside your countries"),
])
def test_does_not_fit(loc, reason):
    r = check(loc)
    assert not r.ok and reason in r.reason


def test_ca_means_canada_next_to_a_province_and_california_next_to_a_us_city():
    assert P.infer_place({"location": "Toronto, ON"}) == ("CA", "Ontario")
    assert P.infer_place({"location": "San Francisco, CA"}) == ("US", "California")
    assert P.infer_place({"location": "Calgary, AB"})[0] == "CA"


def test_infer_place_no_single_country():
    assert P.infer_place({"location": "London, UK; Ontario, CAN"})[0] == ""
    assert P.infer_place({"location": ""}) == ("", "")


def test_remote_modes():
    remote = {"location": "Remote - Canada", "remote": 1}
    onsite = {"location": "Toronto, ON", "remote": 0}
    assert P.check_location(remote, {**CA_ON, "remote": "only"}).ok
    assert not P.check_location(onsite, {**CA_ON, "remote": "only"}).ok
    r = P.check_location(remote, {**CA_ON, "remote": "exclude"})
    assert not r.ok and "remote" in r.reason.lower()
    assert P.check_location(onsite, {**CA_ON, "remote": "exclude"}).ok
    assert P.check_location(remote, CA_ON).ok


def test_hybrid_is_not_fully_remote():
    r = P.check_location({"location": "Hybrid - Toronto, ON"}, {**CA_ON, "remote": "exclude"})
    assert r.ok


def test_no_places_chosen_means_anywhere():
    assert P.check_location({"location": "Tokyo, Japan"}, {"countries": [], "regions": [], "remote": "include"}).ok


def test_city_setting():
    s = {"countries": ["CA"], "regions": [], "cities": ["Waterloo"], "remote": "include"}
    assert P.check_location({"location": "Waterloo, ON"}, s).ok
    assert not P.check_location({"location": "Toronto, ON"}, s).ok


def test_region_given_as_a_code():
    assert P.norm_region("ON") == P.norm_region("Ontario") == "CA-ON"
    s = {"countries": [], "regions": ["ON"], "remote": "include"}
    assert P.check_location({"location": "Toronto, ON"}, s).ok
    assert not P.check_location({"location": "Calgary, AB"}, s).ok
