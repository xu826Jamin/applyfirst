"""Location reading: country, remote, the city-collision vetoes, per-segment reading."""
import pytest

from applyfirst.sources import locations as L


@pytest.mark.parametrize("text,country", [
    ("Toronto, ON", "CA"),
    ("Toronto, Ontario, Canada", "CA"),
    ("Toronto, Ontario CA", "CA"),            # the "Ontario, CA" veto must not eat this
    ("Waterloo, ON", "CA"),
    ("Montréal, QC", "CA"),
    ("Vancouver, BC", "CA"),
    ("Saskatoon, SK", "CA"),
    ("London, Ontario", "CA"),
    ("Alliston, ON", "CA"),
    ("Austin, TX", "US"),
    ("Austin, Texas, United States", "US"),
    ("San Francisco, CA", ""),                 # California or Canada: not guessed
    ("Toronto, CA", "CA"),
    ("New York, NY 10001", "US"),
    ("Santa Fe, New Mexico", "US"),            # not Mexico
    ("Mexico City, Mexico", "MX"),
    ("Remote, US", "US"),
    ("Utrecht, NL", "NL"),
    ("Berlin, DE", ""),                        # Germany or Delaware: not guessed
    ("Berlin, Germany", "DE"),
    ("Sydney, New South Wales", "AU"),
    ("Hamilton", ""),                          # bare ambiguous name
    ("Bratislava, SK", ""),                    # Slovakia or Saskatchewan: not guessed
    ("", ""),
])
def test_country_of_one_location(text, country):
    assert L.parse(text)["country"] == country


@pytest.mark.parametrize("text,country", [
    ("Vancouver, WA", "US"),
    ("Vancouver, Washington", "US"),
    ("London, UK", "GB"),
    ("London, England", "GB"),
    ("Hamilton, OH", "US"),
    ("Hamilton, New Zealand", "NZ"),
    ("Ontario, California", "US"),
    ("Richmond, VA", "US"),
    ("Cambridge, MA", "US"),
    ("Windsor, England", "GB"),
    ("Victoria, Australia", "AU"),
    ("Ottawa, IL", "US"),
])
def test_city_collisions_are_not_canadian(text, country):
    assert L.parse(text)["country"] == country


def test_each_semicolon_segment_is_read_on_its_own():
    r = L.parse("London, UK; Ontario, CAN; Remote-Friendly, United States; San Francisco, CA")
    assert r["countries"] == ["GB", "CA", "US"]
    # the first office is British, but a user who wants Canada gets Canada as the primary
    assert r["country"] == "GB"
    assert L.parse("London, UK; Ontario, CAN", prefer=["CA"])["country"] == "CA"


def test_veto_in_one_segment_does_not_remove_a_real_country_in_another():
    r = L.parse("Vancouver, WA; Vancouver, BC")
    assert r["countries"] == ["US", "CA"]


def test_veto_reads_the_location_only_not_a_hint():
    # a source-supplied "CA" must never turn Ontario, California into Canada
    assert L.parse("Ontario, California", country_hint="CA")["country"] == "US"
    # and the hint is used only when the text names nothing
    assert L.parse("Somewhere Unnamed", country_hint="CA")["country"] == "CA"
    assert L.parse("Toronto, ON", country_hint="US")["country"] == "CA"


def test_oracle_and_workday_prefixed_codes():
    assert L.parse("CA-QC-LONGUEUIL-J01 ~ 1000")["country"] == "CA"
    assert L.parse("US-CT-WINDSOR LOCKS")["country"] == "US"


def test_opaque_workday_location_falls_back_to_the_slug():
    assert L.parse("2 Locations", slug="/job/CA---Esterhazy-SK/Co-op_R1")["country"] == "CA"
    assert L.parse("5 Locations", slug="/job/US---Bartow-FL/Intern_R2")["country"] == "US"
    # both marks, or none: unknown
    assert L.parse("2 Locations", slug="/job/CA---Toronto-ON/US---Austin-TX")["country"] == ""
    assert L.parse("2 Locations", slug="/job/Software-Intern_R3")["country"] == ""
    # a slug never overrides a location that actually says something
    assert L.parse("Austin, TX", slug="/job/CA---Toronto-ON/x")["country"] == "US"


@pytest.mark.parametrize("text,workplace,remote", [
    ("Remote", "", True),
    ("Remote - Canada", "", True),
    ("Remote, US", "", True),
    ("Anywhere", "", True),
    ("Toronto, ON", "", False),
    ("Toronto, ON (Hybrid)", "", False),
    ("Remote-friendly, Toronto", "", False),
    ("Toronto", "remote", True),
    ("Toronto", "hybrid", False),
    ("Remote", "on-site", False),
    ("Toronto, ON; Remote", "", True),
])
def test_remote(text, workplace, remote):
    assert L.is_remote(text, workplace) is remote


def test_remote_country_combo():
    r = L.parse("Remote - Canada")
    assert r["remote"] is True and r["country"] == "CA"


def test_toronto_ontario_comma_ca_stays_canadian():
    assert L.parse("Toronto, Ontario, CA")["country"] == "CA"
    assert L.parse("Ontario, CA")["country"] == "US"
