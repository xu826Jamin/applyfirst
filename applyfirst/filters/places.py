"""Where a posting is, and whether that fits the user's countries, regions, cities and
remote setting.

Calibration rules carried over from an earlier version (hazards 5, 26, 28, 32):
  * Place names collide: Vancouver WA, London UK, Hamilton OH, Ontario CA. A state or province
    code or a country written in the same segment settles it first; a bare city table is only
    a fallback, and names that mean two places are left out of it.
  * A veto reads the location only, never location plus a hint field.
  * A location with several offices ("London, UK; Ontario, CAN") is read one segment at a time:
    the posting fits if ANY segment fits.
  * Two-letter codes that are both a country and a region (CA, NL, DE, IN, IL, CO, AR) are only
    read when the rest of the segment settles which one is meant, otherwise the place stays
    unknown. Unknown is not a mismatch: nothing is skipped on a guess.
  * Workday's "CA-QC-LONGUEUIL-J01 ~ 1000" format is read as country-region-city.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import clip, fold

# --------------------------------------------------------------------------- tables

CA_PROVINCES = {
    "AB": "alberta", "BC": "british columbia", "MB": "manitoba", "NB": "new brunswick",
    "NL": "newfoundland and labrador", "NS": "nova scotia", "NT": "northwest territories",
    "NU": "nunavut", "ON": "ontario", "PE": "prince edward island", "QC": "quebec",
    "SK": "saskatchewan", "YT": "yukon",
}
US_STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "DC": "district of columbia",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho", "IL": "illinois",
    "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york",
    "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon",
    "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina", "SD": "south dakota",
    "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia",
    "WA": "washington", "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming",
}
_REGION_EXTRA = {"newfoundland": ("CA", "NL"), "pei": ("CA", "PE"), "pq": ("CA", "QC"),
                 "washington dc": ("US", "DC"), "washington d.c.": ("US", "DC")}

COUNTRIES = {
    "CA": ["canada", "canadian", "can"],
    "US": ["united states", "united states of america", "usa", "u.s.", "u.s.a.", "us", "america", "any state", "all states", "nationwide", "lower 48", "continental us"],
    "GB": ["united kingdom", "uk", "u.k.", "great britain", "england", "scotland", "wales",
           "northern ireland", "gb"],
    "IE": ["ireland", "ie"], "DE": ["germany", "deutschland"], "FR": ["france"],
    "NL": ["netherlands", "the netherlands", "holland"], "IN": ["india"], "AU": ["australia", "au"],
    "NZ": ["new zealand", "nz"], "SG": ["singapore", "sg"], "JP": ["japan", "jp"],
    "CN": ["china", "cn"], "HK": ["hong kong", "hk"], "KR": ["south korea", "korea", "kr"],
    "IL": ["israel"], "CH": ["switzerland", "ch"], "SE": ["sweden", "se"], "NO": ["norway"],
    "DK": ["denmark", "dk"], "FI": ["finland", "fi"], "ES": ["spain", "es"],
    "IT": ["italy"], "PT": ["portugal", "pt"], "PL": ["poland", "pl"], "BR": ["brazil", "br"],
    "MX": ["mexico", "mx"], "AR": ["argentina"], "CO": ["colombia"], "ZA": ["south africa", "za"],
    "AE": ["united arab emirates", "uae", "ae"], "PH": ["philippines", "ph"],
    "TW": ["taiwan", "tw"], "BE": ["belgium"], "AT": ["austria"], "CZ": ["czech republic",
                                                                         "czechia"],
    "RO": ["romania"], "UA": ["ukraine"], "TR": ["turkey"], "EG": ["egypt"], "NG": ["nigeria"],
    "KE": ["kenya"], "VN": ["vietnam"], "TH": ["thailand"], "MY": ["malaysia"],
    "ID": ["indonesia"], "PK": ["pakistan"], "BD": ["bangladesh"], "CL": ["chile"],
    "PE": ["peru"], "SA": ["saudi arabia"],
}
# Two-letter codes that are also a region code or an ordinary word: read only with context.
_AMBIGUOUS_CODES = {"ca", "nl", "de", "in", "il", "co", "ar", "id", "pe", "no", "it", "sa", "ph"}

_COUNTRY_BY_ALIAS: dict[str, str] = {}
for _iso, _names in COUNTRIES.items():
    for _n in _names:
        if len(_n) == 2 and _n in _AMBIGUOUS_CODES:
            continue
        _COUNTRY_BY_ALIAS[_n] = _iso
for _iso in ("ca", "us"):
    _COUNTRY_BY_ALIAS.pop(_iso, None)
_COUNTRY_BY_ALIAS["us"] = "US"

_REGION_BY_NAME: dict[str, tuple[str, str]] = {}
_REGION_BY_CODE: dict[str, tuple[str, str]] = {}
for _c, _n in CA_PROVINCES.items():
    _REGION_BY_NAME[_n] = ("CA", _c)
    _REGION_BY_CODE[_c.lower()] = ("CA", _c)
for _c, _n in US_STATES.items():
    _REGION_BY_NAME[_n] = ("US", _c)
    _REGION_BY_CODE[_c.lower()] = ("US", _c)
_REGION_BY_NAME.update(_REGION_EXTRA)

# A city table is a fallback for places written with no region or country. Names that mean two
# places (london, hamilton, victoria, portland, richmond, kingston, cambridge, birmingham,
# columbus, springfield, manchester) are left out on purpose.
_CITIES: dict[str, tuple[str, str]] = {}


def _add(country: str, region: str, names: str) -> None:
    for n in names.split("|"):
        _CITIES[fold(n)] = (country, region)


_add("CA", "ON", "toronto|ottawa|mississauga|brampton|markham|vaughan|oakville|burlington|waterloo|"
                 "kitchener|guelph|windsor|richmond hill|barrie|oshawa|kanata|sudbury|st catharines|"
                 "niagara falls|north york|scarborough|etobicoke|pickering|ajax|milton|stittsville|"
                 "kitchener-waterloo|cambridge on|peterborough|kingston on|thornhill|east gwillimbury|"
                 "newmarket|aurora|whitby|concord on")
_add("CA", "BC", "vancouver|burnaby|surrey|kelowna|richmond bc|north vancouver|coquitlam")
_add("CA", "AB", "calgary|edmonton|red deer|lethbridge")
_add("CA", "QC", "montreal|quebec city|laval|gatineau|sherbrooke|longueuil|saint-laurent")
_add("CA", "NS", "halifax|dartmouth")
_add("CA", "MB", "winnipeg")
_add("CA", "SK", "saskatoon|regina")
_add("CA", "NB", "fredericton|moncton|saint john")
_add("CA", "NL", "st johns|st. john's")
_add("US", "CA", "san francisco|san jose|mountain view|palo alto|sunnyvale|santa clara|menlo park|"
                 "cupertino|los angeles|san diego|oakland|redwood city|irvine|santa monica")
_add("US", "NY", "new york|nyc|brooklyn|manhattan|buffalo")
_add("US", "WA", "seattle|redmond|bellevue|kirkland")
_add("US", "TX", "austin|dallas|houston|san antonio|plano")
_add("US", "MA", "boston|cambridge ma")
_add("US", "IL", "chicago")
_add("US", "CO", "denver|boulder")
_add("US", "GA", "atlanta")
_add("US", "FL", "miami|orlando|tampa")
_add("US", "NC", "raleigh|durham|charlotte")
_add("US", "PA", "pittsburgh|philadelphia")
_add("US", "DC", "washington dc|washington d.c.")
_add("US", "AZ", "phoenix|tempe")
_add("US", "MN", "minneapolis")
_add("US", "MI", "detroit|ann arbor")
_add("US", "UT", "salt lake city")
_add("GB", "", "edinburgh|glasgow|bristol|leeds")
_add("DE", "", "berlin|munich|hamburg|frankfurt|cologne|stuttgart")
_add("FR", "", "paris|lyon|toulouse|marseille")
_add("NL", "", "amsterdam|rotterdam|utrecht|eindhoven")
_add("IE", "", "dublin|cork")
_add("IN", "", "bangalore|bengaluru|hyderabad|pune|mumbai|delhi|new delhi|gurgaon|gurugram|chennai|"
               "noida")
_add("AU", "", "sydney|melbourne|brisbane|perth")
_add("NZ", "", "auckland|wellington")
_add("SG", "", "singapore")
_add("JP", "", "tokyo|osaka")
_add("CN", "", "beijing|shanghai|shenzhen")
_add("HK", "", "hong kong")
_add("KR", "", "seoul")
_add("IL", "", "tel aviv")
_add("CH", "", "zurich|geneva")
_add("SE", "", "stockholm")
_add("ES", "", "madrid|barcelona")
_add("IT", "", "milan|rome")
_add("PL", "", "warsaw|krakow")
_add("PT", "", "lisbon")
_add("DK", "", "copenhagen")
_add("FI", "", "helsinki")
_add("NO", "", "oslo")
_add("AE", "", "dubai")
_add("BR", "", "sao paulo")
_add("MX", "", "mexico city")
_add("ZA", "", "johannesburg|cape town")

_REMOTE = re.compile(
    r"\b(?:remote(?:ly)?|work\s+from\s+home|wfh|anywhere|virtual|home[\s-]?based|"
    r"t[e]letravail|distributed)\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_NOISE = re.compile(
    r"\b(?:remote|hybrid|on[\s-]?site|onsite|work\s+from\s+home|wfh|flexible|anywhere|virtual|"
    r"home[\s-]?based|full[\s-]?time|part[\s-]?time|multiple\s+locations?|various|office|"
    r"headquarters|hq|region|area|greater|metropolitan|metro|city\s+of|distributed|"
    r"locations?|and|or)\b", re.I)


# --------------------------------------------------------------------------- reading a place


@dataclass
class Place:
    raw: str
    remote: bool = False
    country: str = ""            # ISO code, '' when unknown
    region: str = ""             # 'CA-ON', '' when unknown
    cities: list[str] = field(default_factory=list)   # folded names left over
    text: str = ""               # the whole folded segment, for 'greater toronto area'

    @property
    def specific(self) -> bool:
        """True when the place names somewhere definite (so a non-match is a real mismatch)."""
        return bool(self.region or (self.cities and self.country))


def split_segments(location: str) -> list[str]:
    parts = re.split(r"\s*(?:;|\||\s/\s|\n)\s*", str(location or ""))
    return [p.strip() for p in parts if p and p.strip()]


def _peel(tok: str) -> tuple[str, list[tuple[str, str]]]:
    """Strip trailing country or region names from a token with no commas
    ('toronto ontario canada' -> 'toronto' plus ontario and canada)."""
    found: list[tuple[str, str]] = []
    words = tok.split()
    while len(words) >= 2:
        for n in (3, 2, 1):
            if len(words) <= n:
                continue
            tail = " ".join(words[-n:])
            if tail in _COUNTRY_BY_ALIAS and len(tail) > 2:
                found.append(("country", _COUNTRY_BY_ALIAS[tail]))
            elif tail in _REGION_BY_NAME:
                found.append(("region", "-".join(_REGION_BY_NAME[tail])))
            else:
                continue
            words = words[:-n]
            break
        else:
            break
    return " ".join(words), found


def parse_place(seg: str) -> Place:
    raw = str(seg or "").strip()
    low = fold(raw)
    p = Place(raw=raw, text=low)
    p.remote = bool(_REMOTE.search(low))

    # Workday: "CA-QC-LONGUEUIL-J01 ~ 1000"
    m = re.match(r"^([a-z]{2})-([a-z]{2,3})-([a-z][a-z .'\-]*?)(?:-[a-z0-9]+)?(?:\s*~.*)?$", low)
    if m:
        iso, reg = m.group(1).upper(), m.group(2).upper()
        if iso in COUNTRIES and (reg in CA_PROVINCES or reg in US_STATES) and \
                _REGION_BY_CODE.get(reg.lower(), ("", ""))[0] == iso:
            p.country, p.region = iso, f"{iso}-{reg}"
            p.cities = [m.group(3).replace("-", " ").strip()]
            return p

    tokens = [t.strip() for t in re.split(r",|\s+-\s+|\s+–\s+|[()]|/", low) if t.strip()]
    countries: list[str] = []
    regions: list[str] = []
    cities: list[str] = []
    ambiguous: list[tuple[int, str]] = []
    for i, tok in enumerate(tokens):
        if tok in _REGION_BY_NAME or tok in _COUNTRY_BY_ALIAS:
            clean = tok
        else:
            clean = re.sub(r"\s+", " ", _NOISE.sub(" ", tok)).strip(" .-")
        if not clean:
            continue
        if len(clean) == 2 and clean in _AMBIGUOUS_CODES:
            ambiguous.append((i, clean))
            continue
        if clean in _COUNTRY_BY_ALIAS:
            countries.append(_COUNTRY_BY_ALIAS[clean])
            continue
        if clean in _REGION_BY_NAME:
            regions.append("-".join(_REGION_BY_NAME[clean]))
            continue
        if len(clean) == 2 and clean in _REGION_BY_CODE and i >= 1:
            regions.append("-".join(_REGION_BY_CODE[clean]))
            continue
        base, extra = _peel(clean)
        for kind, val in extra:
            (countries if kind == "country" else regions).append(val)
        if base:
            cities.append(base)

    # A city table fallback only when no region was named, and only for a city in the named
    # country ("Toronto, Canada" is Ontario; "Toronto, Italy" is not).
    if not regions:
        for c in cities:
            hit = _CITIES.get(c)
            if hit and (not countries or hit[0] in countries):
                if not countries:
                    countries.append(hit[0])
                if hit[1]:
                    regions.append(f"{hit[0]}-{hit[1]}")
                break

    # Resolve two-letter codes that are both a country and a region from the rest of the segment.
    for i, code in ambiguous:
        prior_city = next((c for c in cities if c in _CITIES), "")
        city_country = _CITIES.get(prior_city, ("", ""))[0]
        later_country = any(
            _COUNTRY_BY_ALIAS.get(t) for t in tokens[i + 1:])
        if code == "ca":
            if any(r.startswith("CA-") for r in regions) or city_country == "CA":
                countries.append("CA")
            elif later_country or city_country == "US" or any(r.startswith("US-") for r in regions):
                regions.append("US-CA")
            elif len(tokens) == 1:
                countries.append("CA")
            # else: Toronto-less "Smalltown, CA" stays unknown.
            continue
        iso = code.upper()
        if city_country == iso and iso in COUNTRIES:
            countries.append(iso)
        elif code in _REGION_BY_CODE and (later_country or city_country in ("US", "CA")):
            regions.append("-".join(_REGION_BY_CODE[code]))
        # otherwise unknown on purpose

    if regions:
        p.region = regions[0]
    if countries:
        p.country = countries[0]
    elif p.region:
        p.country = p.region.split("-")[0]
    p.cities = [c for c in cities if c]
    return p


# --------------------------------------------------------------------------- the user's side


def norm_country(value: object) -> str:
    v = fold(value).strip()
    if not v:
        return ""
    if v in ("uk", "gb"):
        return "GB"
    if len(v) == 2 and v.upper() in COUNTRIES:
        return v.upper()
    if v in _COUNTRY_BY_ALIAS:
        return _COUNTRY_BY_ALIAS[v]
    if v in ("canada",):
        return "CA"
    return v.upper() if len(v) == 2 else v


def norm_region(value: object) -> str:
    """'Ontario' or 'ON' -> 'CA-ON'; 'California' or 'CA' -> 'US-CA'; unknown names stay as
    folded text and are matched against the posting's words."""
    v = fold(value).strip()
    if not v:
        return ""
    if v in _REGION_BY_NAME:
        return "-".join(_REGION_BY_NAME[v])
    if len(v) == 2 and v in _REGION_BY_CODE:
        return "-".join(_REGION_BY_CODE[v])
    return v


@dataclass
class Wants:
    countries: set[str]
    regions: set[str]
    cities: list[str]
    remote: str

    @classmethod
    def from_search(cls, search: dict) -> "Wants":
        return cls(
            countries={c for c in (norm_country(x) for x in search.get("countries") or []) if c},
            regions={r for r in (norm_region(x) for x in search.get("regions") or []) if r},
            cities=[c for c in (fold(x).strip() for x in search.get("cities") or []) if c],
            remote=str(search.get("remote") or "include").lower(),
        )

    @property
    def any_place(self) -> bool:
        return bool(self.countries or self.regions or self.cities)


def _region_match(p: Place, wants: Wants) -> bool:
    for r in wants.regions:
        if "-" in r and r[:2].isupper():
            if p.region == r:
                return True
        elif r and re.search(r"(?<![a-z0-9])" + re.escape(r) + r"(?![a-z0-9])", p.text):
            return True
    return False


def _city_match(p: Place, wants: Wants) -> bool:
    for c in wants.cities:
        if c in p.cities or re.search(r"(?<![a-z0-9])" + re.escape(c) + r"(?![a-z0-9])", p.text):
            return True
    return False


@dataclass
class LocationResult:
    ok: bool
    reason: str = ""           # why not, in plain words
    kept: str = ""             # why yes, in plain words
    remote: bool = False       # the posting is (or offers) remote work
    fully_remote: bool = False
    code: str = ""             # 'location', 'country', 'remote-only', 'remote-excluded'


def is_remote(posting: dict) -> tuple[bool, bool]:
    """(offers remote, fully remote) from the remote flag and the location text."""
    places = [parse_place(s) for s in split_segments(posting.get("location"))]
    flag = bool(posting.get("remote"))
    any_remote = flag or any(p.remote and not _HYBRID.search(p.text) for p in places)
    all_remote = flag or (bool(places) and all(p.remote and not _HYBRID.search(p.text) for p in places))
    return any_remote, all_remote


def check_location(posting: dict, search: dict) -> LocationResult:
    wants = Wants.from_search(search)
    loc_text = str(posting.get("location") or "")
    places = [parse_place(s) for s in split_segments(loc_text)]
    any_remote, fully_remote = is_remote(posting)
    shown = clip(loc_text, 50) if loc_text.strip() else ""

    if wants.remote == "exclude" and fully_remote:
        return LocationResult(False, "Remote role, and you chose to leave remote roles out",
                              remote=True, fully_remote=True, code="remote-excluded")
    if wants.remote == "only" and not any_remote:
        why = f"Not a remote role ({shown})" if shown else "Not marked as a remote role"
        return LocationResult(False, why, code="remote-only")

    posting_country = norm_country(posting.get("country"))
    if not wants.any_place:
        kept = "Remote role" if fully_remote else (f"Location: {shown}" if shown else "")
        return LocationResult(True, kept=kept, remote=any_remote, fully_remote=fully_remote)

    if not places:
        places = [Place(raw="", country=posting_country)]
    elif posting_country and len(places) == 1 and not places[0].country:
        places[0].country = posting_country

    # A place we cannot read ("Cairo - ETIC", "2 Locations", "Cleveland Clinic Main Campus") is
    # kept only when the posting's own text names somewhere the user wants. Keeping every
    # unreadable place filled a live Ontario search with Zurich, Cairo and Ohio postings.
    confirmed = None

    def text_confirms() -> bool:
        nonlocal confirmed
        if confirmed is None:
            confirmed = _confirmed_by_text(posting, wants)
        return confirmed

    country_fail = unconfirmed = False
    for p in places:
        as_remote = fully_remote or (p.remote and not _HYBRID.search(p.text))
        country = p.country
        if wants.countries and country and country not in wants.countries:
            country_fail = True
            continue
        if as_remote:
            return LocationResult(True, kept="Remote role", remote=any_remote, fully_remote=fully_remote)
        if not (wants.regions or wants.cities):
            if country or (not wants.countries) or text_confirms():
                return LocationResult(True, kept=(f"Location: {shown}" if shown else ""),
                                      remote=any_remote, fully_remote=fully_remote)
            unconfirmed = True
            continue
        if _region_match(p, wants) or _city_match(p, wants):
            return LocationResult(True, kept=f"Location: {shown}", remote=any_remote,
                                  fully_remote=fully_remote)
        if not p.specific:
            if text_confirms():
                return LocationResult(True, kept=(f"Location: {shown}" if shown else "Location named in the posting"),
                                      remote=any_remote, fully_remote=fully_remote)
            unconfirmed = True
    if country_fail and not unconfirmed and not any(
            not (wants.countries and pl.country and pl.country not in wants.countries)
            for pl in places):
        return LocationResult(False, f"Outside your countries: {shown or 'unknown place'}",
                              remote=any_remote, fully_remote=fully_remote, code="country")
    if unconfirmed:
        return LocationResult(False, f"Location not confirmed in your area: {shown or 'not stated'}",
                              remote=any_remote, fully_remote=fully_remote, code="location-unknown")
    return LocationResult(False, f"Outside your locations: {shown or 'unknown place'}",
                          remote=any_remote, fully_remote=fully_remote, code="location")


def _confirmed_by_text(posting: dict, wants: Wants) -> bool:
    """True when the posting's title or description names a place the user wants."""
    text = fold(" ".join(str(posting.get(k) or "") for k in ("title", "description", "location")))
    if not text.strip():
        return False
    names: list[str] = list(wants.cities)
    abbrevs: list[str] = []
    for r in wants.regions:
        if "-" in r and r[:2].isupper():
            c, code = r.split("-", 1)
            full = (CA_PROVINCES if c == "CA" else US_STATES if c == "US" else {}).get(code)
            if full:
                names.append(full)
            abbrevs.append(code.lower())
            # the region's known cities ("Toronto" confirms Ontario)
            names += [city for city, (cc, rc) in _CITIES.items() if cc == c and rc == code]
        elif r:
            names.append(r)
    if not names:
        for c in wants.countries:
            names += [n for n in COUNTRIES.get(c, []) if len(n) > 3 and n not in _AMBIGUOUS_CODES]
            table = CA_PROVINCES if c == "CA" else US_STATES if c == "US" else {}
            names += list(table.values())
    for n in names:
        if re.search(r"(?<![a-z0-9])" + re.escape(fold(n)) + r"(?![a-z0-9])", text):
            return True
    # "Toronto, ON" style: a region code right after a comma, read in the location field only
    # (in prose ", on" is just the word "on")
    loc = fold(str(posting.get("location") or ""))
    return any(re.search(r",\s*" + re.escape(a) + r"(?![a-z0-9])", loc) for a in abbrevs)


def infer_place(posting: dict) -> tuple[str, str]:
    """(country ISO code, region name) read from the location text; '' where not settled.
    Several offices in different countries give no single country."""
    places = [parse_place(s) for s in split_segments(posting.get("location"))]
    countries = {p.country for p in places if p.country}
    country = next(iter(countries)) if len(countries) == 1 else ""
    region = ""
    regions = {p.region for p in places if p.region}
    if len(regions) == 1:
        code = next(iter(regions))
        c, r = code.split("-")
        region = (CA_PROVINCES if c == "CA" else US_STATES).get(r, "").title()
    return country, region
