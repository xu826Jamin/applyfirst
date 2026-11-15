"""Where is this posting? Country (ISO 3166 alpha-2) and remote, read from a location string.

Hard-won rules carried over from the pipeline this was built from; each one is a real failure:

* A place-name list is a regression record, not a rule. City names collide: Vancouver WA,
  London UK, Hamilton OH, Ontario California, Richmond VA, Cambridge MA. A name that exists in
  two countries counts only when something in the same segment says which one it is; a bare
  ambiguous name leaves the country empty rather than guessed.
* A posting can list several offices: "London, UK; Ontario, CAN; Remote, United States". Each
  semicolon segment is read on its own, so a veto in one segment never reaches across into the
  next, and every country found is kept.
* The veto reads the location text only, never a board-level hint. (A hint of "CA" once vetoed
  eleven real Toronto roles through an "Ontario, CA" pattern.)
* Workday hides the location behind "2 Locations"; the posting URL slug then carries the only
  signal ("CA---Esterhazy-SK", "US---Bartow-FL"). A slug with both marks or none stays unknown.
* A retrieval failure stays empty. Unknown is "", never a guess.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- vocabulary

COUNTRIES: dict[str, str] = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.a.": "US",
    "u.s.": "US",
    "canada": "CA", "canadian": "CA",
    "united kingdom": "GB", "great britain": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "new south wales": "AU", "northern ireland": "GB", "uk": "GB",
    "gbr": "GB", "u.k.": "GB",
    "ireland": "IE", "germany": "DE", "deutschland": "DE", "france": "FR", "spain": "ES",
    "italy": "IT", "portugal": "PT", "netherlands": "NL", "the netherlands": "NL",
    "belgium": "BE", "luxembourg": "LU", "switzerland": "CH",
    "austria": "AT", "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI",
    "iceland": "IS", "poland": "PL", "czech republic": "CZ", "czechia": "CZ",
    "slovakia": "SK", "hungary": "HU", "romania": "RO", "bulgaria": "BG", "greece": "GR",
    "croatia": "HR", "serbia": "RS", "slovenia": "SI", "estonia": "EE", "latvia": "LV",
    "lithuania": "LT", "ukraine": "UA", "turkey": "TR", "turkiye": "TR", "israel": "IL",
    "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA", "egypt": "EG",
    "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "morocco": "MA",
    "india": "IN", "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK",
    "china": "CN", "hong kong": "HK", "taiwan": "TW", "japan": "JP", "south korea": "KR",
    "korea": "KR", "singapore": "SG", "malaysia": "MY", "indonesia": "ID",
    "philippines": "PH", "thailand": "TH", "vietnam": "VN", "australia": "AU",
    "new zealand": "NZ", "mexico": "MX", "brazil": "BR", "brasil": "BR", "argentina": "AR",
    "chile": "CL", "colombia": "CO", "peru": "PE", "uruguay": "UY", "costa rica": "CR",
    "panama": "PA", "ecuador": "EC", "puerto rico": "PR",
}
# Codes that are unambiguous after a comma ("Amsterdam, NL"). Codes that are also a US state or
# a Canadian province (CA, DE, IN, IL, CO, AR, AL, MA, MD, PA, PE, SK, ...) are left out on
# purpose: "Wilmington, DE" and "Berlin, DE" cannot be told apart without the city.
ISO2_SAFE = {
    "GB": "GB", "UK": "GB", "IE": "IE", "FR": "FR", "ES": "ES", "IT": "IT", "PT": "PT",
    "NL": "NL", "BE": "BE", "CH": "CH", "AT": "AT", "SE": "SE", "NO": "NO", "DK": "DK",
    "FI": "FI", "PL": "PL", "CZ": "CZ", "HU": "HU", "RO": "RO", "BG": "BG", "GR": "GR",
    "UA": "UA", "TR": "TR", "AE": "AE", "SA": "SA", "EG": "EG", "ZA": "ZA", "NG": "NG",
    "KE": "KE", "PK": "PK", "BD": "BD", "CN": "CN", "HK": "HK", "TW": "TW", "JP": "JP",
    "KR": "KR", "SG": "SG", "MY": "MY", "PH": "PH", "TH": "TH", "VN": "VN", "AU": "AU",
    "NZ": "NZ", "MX": "MX", "BR": "BR", "CL": "CL", "US": "US",
    "CAN": "CA", "USA": "US", "IND": "IN", "DEU": "DE", "FRA": "FR", "GBR": "GB",
}

CA_PROVINCES = {
    "alberta": "AB", "british columbia": "BC", "manitoba": "MB", "new brunswick": "NB",
    "newfoundland": "NL", "newfoundland and labrador": "NL", "nova scotia": "NS",
    "northwest territories": "NT", "nunavut": "NU", "ontario": "ON",
    "prince edward island": "PE", "quebec": "QC", "québec": "QC", "saskatchewan": "SK",
    "yukon": "YT",
}
# NL (Netherlands), PE (Peru) and SK (Slovakia) are absent from the bare-code rule.
CA_CODES = {"AB", "BC", "MB", "NB", "NS", "NT", "NU", "ON", "QC", "YT"}

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "west virginia": "WV", "washington": "WA", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC",
}
US_CODES = set(US_STATES.values())
# State codes that are also something else; read only with a city or a country beside them.
AMBIGUOUS_CODES = {"CA", "DE", "IN", "IL", "CO", "AR", "AL", "MA", "MD", "PA", "ME", "MT",
                   "LA", "NE", "SC", "SD", "NC", "ND", "MO", "MN", "NM", "AZ", "GA", "ID"}

# Canadian places that exist only in Canada (safe on their own).
CA_CITIES_SAFE = {
    "toronto", "montreal", "montréal", "calgary", "edmonton", "winnipeg",
    "mississauga", "brampton", "markham", "vaughan", "kitchener", "oakville", "burnaby",
    "saskatoon", "regina", "longueuil", "laval", "gatineau", "sherbrooke",
    "moncton", "fredericton", "kanata", "kelowna", "coquitlam", "richmond hill",
    "north york", "scarborough", "etobicoke", "mont-royal", "saint-laurent", "dorval",
    "pointe-claire", "nanaimo", "st. john's", "st john's", "charlottetown", "whitehorse",
    "yellowknife", "iqaluit", "thunder bay", "sudbury", "oshawa", "barrie", "guelph",
    "st. catharines", "quebec city", "trois-rivieres", "saint-jerome",
    "saint-jérôme", "lethbridge", "red deer", "medicine hat", "airdrie", "chatham-kent",
}
# Names that also exist elsewhere; Canadian only beside a province or "Canada" (read earlier).
CA_CITIES_AMBIGUOUS = {
    "vancouver", "hamilton", "london", "victoria", "richmond", "cambridge", "waterloo",
    "windsor", "kingston", "burlington", "milton", "delta", "peterborough", "ontario",
    "aurora", "mission", "vernon", "woodstock", "cornwall", "orillia", "belleville",
    "surrey", "halifax", "ottawa",
}

# City, region pairs that LOOK Canadian and are not. Each is a real false positive seen in
# production data. The value is the country the pair actually belongs to.
VETOES: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.I), c) for p, c in [
        (r"\bontario,\s*(california|ca)\b(?!nada)", "US"),
        (r"\bvancouver,?\s*(wa|washington)\b", "US"),
        (r"\blondon,?\s*(uk|england|gb|united kingdom)\b", "GB"),
        (r"\blondon,?\s*(ky|kentucky|oh|ohio)\b", "US"),
        (r"\bhamilton,?\s*(nz|new zealand)\b", "NZ"),
        (r"\bhamilton,?\s*bermuda\b", "BM"),
        (r"\bhamilton,?\s*(oh|ohio|mt|montana)\b", "US"),
        (r"\brichmond,?\s*(va|virginia|ca|california|tx|texas|in|indiana|ky|kentucky)\b", "US"),
        (r"\bwaterloo,?\s*(ia|iowa|il|illinois|ny|new york)\b", "US"),
        (r"\bwaterloo,?\s*(belgium|be)\b", "BE"),
        (r"\bkingston,?\s*(ny|new york|pa|pennsylvania)\b", "US"),
        (r"\bkingston,?\s*jamaica\b", "JM"),
        (r"\bcambridge,?\s*(ma|massachusetts|md|maryland)\b", "US"),
        (r"\bcambridge,?\s*(uk|england|gb)\b", "GB"),
        (r"\bvictoria,?\s*(tx|texas)\b", "US"),
        (r"\bvictoria,?\s*(australia|au)\b", "AU"),
        (r"\bpeterborough,?\s*(nh|new hampshire)\b", "US"),
        (r"\bpeterborough,?\s*(uk|england)\b", "GB"),
        (r"\bwindsor,?\s*(ct|connecticut|co|colorado)\b", "US"),
        (r"\bwindsor,?\s*(uk|england|berkshire)\b", "GB"),
        (r"\bwindsor locks\b", "US"),
        (r"\bburlington,?\s*(vt|vermont|nc|north carolina|nj|new jersey|ma|massachusetts)\b", "US"),
        (r"\bmilton,?\s*(ma|massachusetts|ga|georgia)\b", "US"),
        (r"\bdelta,?\s*(ut|utah|co|colorado|oh|ohio)\b", "US"),
        (r"\brichmond hill,?\s*(ga|georgia|ny|new york)\b", "US"),
        (r"\baurora,?\s*(co|colorado|il|illinois)\b", "US"),
        (r"\bwoodstock,?\s*(ga|georgia|ny|new york|il|illinois)\b", "US"),
        (r"\bcornwall,?\s*(uk|england)\b", "GB"),
        (r"\bmission,?\s*(tx|texas|ks|kansas)\b", "US"),
        (r"\bottawa,?\s*(il|illinois|ks|kansas)\b", "US"),
        (r"\bhalifax,?\s*(uk|england)\b", "GB"),
        (r"\bsurrey,?\s*(uk|england)\b", "GB"),
    ]
]

REMOTE_RE = re.compile(
    r"\b(remote|work from home|wfh|work-from-home|anywhere|distributed|virtual)\b", re.I)
# "Remote-friendly" / "remote optional" / hybrid describe an office job, not a remote one.
NOT_REMOTE_RE = re.compile(r"remote[- ](friendly|optional|possible|eligible)|hybrid", re.I)

OPAQUE_RE = re.compile(r"^\d+\s+locations?$", re.I)
SEGMENT_SPLIT = re.compile(r"\s*(?:;|\||\n|\s/\s)\s*")


def _alt(names, longest_first=True) -> str:
    ordered = sorted(names, key=len, reverse=True) if longest_first else list(names)
    return "|".join(re.escape(n) for n in ordered)


_COUNTRY_RE = re.compile(r"(?<![\w.])(" + _alt(COUNTRIES) + r")(?![\w])", re.I)
_PROVINCE_RE = re.compile(r"(?<!\w)(" + _alt(CA_PROVINCES) + r")(?!\w)", re.I)
_STATE_RE = re.compile(r"(?<!\w)(" + _alt(US_STATES) + r")(?!\w)", re.I)
_SAFE_CITY_RE = re.compile(r"(?<!\w)(" + _alt(CA_CITIES_SAFE) + r")(?!\w)", re.I)
# Oracle Cloud and Workday write "CA-QC-LONGUEUIL-J01 ~ 1000" and "US-CT-WINDSOR LOCKS".
_PREFIXED_RE = re.compile(r"(?:^|[\s(])([A-Z]{2})[-_]([A-Z]{2})(?:[-_]|\b)")
_TRAILING_CODE_RE = re.compile(
    r",\s*([A-Z]{2,3})\s*(?:\d{4,5}(?:-\d{4})?|[A-Z]\d[A-Z]\s*\d[A-Z]\d)?\s*$")
_BARE_US_RE = re.compile(r"(?<![\w.])US(?![\w.])")
_SLUG_CA_RE = re.compile(r"(?:^|[-_/])(ab|bc|mb|nb|ns|nl|nt|nu|on|pe|qc|sk|yt)(?:[-_/]|$)", re.I)
_SLUG_US_RE = re.compile(r"(?:^|[/_.-])us-{1,3}[a-z]", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def segments(location: str) -> list[str]:
    parts = [p.strip() for p in SEGMENT_SPLIT.split(location or "") if p and p.strip()]
    return parts or ([_norm(location)] if _norm(location) else [])


def segment_country(seg: str) -> str:
    """Country of one location segment, or '' when it cannot be told."""
    seg = _norm(seg)
    if not seg:
        return ""
    for pat, country in VETOES:
        vm = pat.search(seg)
        # "Toronto, Ontario, CA": a Canadian-only city ahead of the match outranks the veto.
        if vm and not _SAFE_CITY_RE.search(seg[: vm.start()]):
            return country
    masked = re.sub(r"new mexico", "New_Mexico_State", seg, flags=re.I)

    m = _PREFIXED_RE.search(seg)
    if m:
        a, b = m.group(1), m.group(2)
        if a == "CA" and b in CA_CODES:
            return "CA"
        if a == "US" and b in US_CODES:
            return "US"
    if re.match(r"^\s*US[-_]", seg) or _BARE_US_RE.search(seg):
        return "US"

    # An explicit country name wins over anything inferred from a region or city.
    explicit = sorted({COUNTRIES[c.lower()] for c in _COUNTRY_RE.findall(masked)})
    if explicit:
        return explicit[0]

    tm = _TRAILING_CODE_RE.search(seg)
    code = tm.group(1) if tm else ""
    if _PROVINCE_RE.search(seg) or code in CA_CODES:
        return "CA"
    us_evidence = bool(_STATE_RE.search(masked)) or "New_Mexico_State" in masked or (
        code in US_CODES and code not in AMBIGUOUS_CODES)
    if _SAFE_CITY_RE.search(seg) and not us_evidence:
        return "CA"
    if code in ISO2_SAFE:
        return ISO2_SAFE[code]
    if us_evidence:
        return "US"
    if code == "CA":
        # "Toronto, CA" is Canada, "San Francisco, CA" is California; the city decides.
        head = seg[: tm.start()] if tm else seg
        return "CA" if _SAFE_CITY_RE.search(head) else ""
    return ""


def slug_country(slug: str) -> str:
    """Country from a URL or job-id slug, used only when the location itself is opaque."""
    if not slug:
        return ""
    low = slug.lower()
    # A bare "CA" prefix is as ambiguous as the city names (three US states abbreviated
    # "CA-OK-ND" once read as Canada), so only a province code counts as a Canadian mark.
    has_ca = bool(_SLUG_CA_RE.search(low))
    has_us = bool(_SLUG_US_RE.search(low))
    if has_ca and not has_us:
        return "CA"
    if has_us and not has_ca:
        return "US"
    return ""


def is_remote(location: str, workplace: str = "") -> bool:
    """True when the location text (or an explicit workplace type) says remote."""
    if workplace:
        w = workplace.lower()
        if "remote" in w and "hybrid" not in w:
            return True
        if w in ("hybrid", "on-site", "onsite", "on_site"):
            return False
    for seg in segments(location):
        if NOT_REMOTE_RE.search(seg):
            continue
        if REMOTE_RE.search(seg):
            return True
    return False


def parse(location: str, *, slug: str = "", country_hint: str = "", workplace: str = "",
          remote_hint: bool | None = None, prefer: list[str] | None = None) -> dict:
    """{"country": "CA", "countries": ["GB", "CA"], "remote": True}

    `country_hint` is an ISO code the source itself supplied (Lever's country field, a
    SmartRecruiters location.country). It is used only when the text names no country.
    `prefer` is the user's wanted countries: when a posting lists several, a wanted one is
    chosen as the primary country."""
    segs = segments(location)
    found: list[str] = []
    for s in segs:
        c = segment_country(s)
        if c and c not in found:
            found.append(c)
    if not found and len(segs) == 1 and OPAQUE_RE.match(segs[0]):
        c = slug_country(slug)
        if c:
            found.append(c)
    hint = (country_hint or "").strip().upper()
    if not found and re.fullmatch(r"[A-Z]{2}", hint):
        found.append("GB" if hint == "UK" else hint)
    primary = ""
    if found:
        wanted = [p.upper() for p in (prefer or [])]
        primary = next((c for c in found if c in wanted), found[0])
    remote = is_remote(location, workplace)
    if remote_hint:
        remote = True
    return {"country": primary, "countries": found, "remote": remote}
