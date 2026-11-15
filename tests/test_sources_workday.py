"""Workday: 20 per page, fuzzy search, the country facet, the offset-2000 clamp, bodies on request."""
from test_sources_fakes import FakeHttp

from applyfirst.sources import fetchers as F
from applyfirst.sources import workday as W
from applyfirst.sources.net import FetchError

BOARD = {"ats": "workday", "token": "acme", "wd": "wd3", "site": "Careers", "company": "Acme"}
URL = "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"


def job(n, title="Software Intern", loc="Toronto, ON, Canada"):
    return {"title": f"{title} {n}", "locationsText": loc, "externalPath": f"/job/Toronto/{title.replace(' ', '-')}-{n}_R{n}",
            "postedOn": "Posted 2 Days Ago"}


def pager(total, make=job, facets=None, record=None):
    def answer(url, payload):
        if record is not None:
            record.append(payload)
        off = payload["offset"]
        n = min(20, max(0, total - off))
        return {"total": total, "jobPostings": [make(off + i) for i in range(n)], "facets": facets or []}
    return answer


def test_pages_of_twenty_until_a_short_page_and_builds_public_links():
    seen = []
    http = FakeHttp({URL: pager(45, record=seen)})
    res = W.fetch(BOARD, F.Ctx(http=http, terms=["intern"], countries=["US"]))
    assert len(res.postings) == 45
    assert [p["offset"] for p in seen] == [0, 20, 40] and all(p["limit"] == 20 for p in seen)
    p = res.postings[0]
    assert p["url"].startswith("https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/Toronto/")
    assert p["posted_at"] and p["slug"] == p["ref"]
    assert not res.complete                                    # a search is not the whole board


def test_whole_board_read_is_complete_and_has_no_country_facet_for_non_canada():
    seen = []
    http = FakeHttp({URL: pager(5, record=seen)})
    res = W.fetch(BOARD, F.Ctx(http=http, terms=[], countries=["US"]))
    assert res.complete and seen[0]["appliedFacets"] == {} and seen[0]["searchText"] == ""


def test_canada_only_users_get_the_country_facet_and_it_is_dropped_when_the_tenant_refuses_it():
    seen = []

    def answer(url, payload):
        seen.append(payload)
        if payload["appliedFacets"]:
            raise FetchError("bad facet", "http400", 400)
        return {"total": 1, "jobPostings": [job(1)], "facets": []}
    res = W.fetch(BOARD, F.Ctx(http=FakeHttp({URL: answer}), terms=["intern"], countries=["CA"]))
    assert "locationCountry" in seen[0]["appliedFacets"]
    assert seen[1]["appliedFacets"] == {} and len(res.postings) == 1


def test_a_server_error_is_a_failed_board_not_an_empty_one():
    import pytest
    with pytest.raises(FetchError):
        W.fetch(BOARD, F.Ctx(http=FakeHttp({URL: FetchError("boom", "http500", 500)}), terms=[], countries=[]))


def test_clamp_is_detected_from_facets_and_recovered_by_splitting():
    facets = [{"facetParameter": "jobFamily", "values": [{"id": "eng", "count": 30}, {"id": "ops", "count": 30}]}]

    def answer(url, payload):
        fam = (payload["appliedFacets"].get("jobFamily") or [None])[0]
        if fam is None:
            return {"total": 2000, "jobPostings": [job(i, "Root") for i in range(20)], "facets": facets * 40}
        base = 1000 if fam == "eng" else 2000
        off = payload["offset"]
        n = min(20, max(0, 30 - off))
        return {"total": 30, "jobPostings": [job(base + off + i, fam) for i in range(n)], "facets": []}
    # root claims 2000 with 20 per page, so it pages until the cap; make the root short-circuit by
    # reporting a total the facets contradict, then ending the pages
    def root_then_slices(url, payload):
        fam = (payload["appliedFacets"].get("jobFamily") or [None])[0]
        if fam is None:
            if payload["offset"] >= 20:
                return {"total": 2000, "jobPostings": [], "facets": []}
            return {"total": 2000, "jobPostings": [job(i, "Root") for i in range(20)],
                    "facets": [{"facetParameter": "jobFamily", "values": [{"id": "eng", "count": 1500}, {"id": "ops", "count": 1500}]}]}
        return answer(url, payload)
    http = FakeHttp({URL: root_then_slices})
    res = W.fetch(BOARD, F.Ctx(http=http, terms=[], countries=[]))
    titles = {p["title"].split()[0] for p in res.postings}
    assert {"Root", "eng", "ops"} <= titles                     # the slices were read too
    assert len(res.postings) == 20 + 30 + 30
    assert "clamped" in res.note


def test_clamp_helpers():
    facets = [{"facetParameter": "a", "values": [{"id": "x", "count": 2624}]}]
    assert W.true_total_from_facets(facets) == 2624
    assert W.clamp_note(2000, facets) and "2624" in W.clamp_note(2000, facets)
    assert W.clamp_note(1005, facets) is None and W.clamp_note(2000, []) is None
    parts = [{"facetParameter": "g", "values": [{"descriptor": "header"}, {"id": "a", "count": 900}, {"id": "b", "count": 100}]},
             {"facetParameter": "t", "values": [{"id": "f", "count": 700}, {"id": "p", "count": 300}]},
             {"facetParameter": "one", "values": [{"id": "only", "count": 1000}]}]
    assert W.choose_split_facet(parts)["facetParameter"] == "t"           # smallest largest slice
    assert W.choose_split_facet(parts, exclude=["t"])["facetParameter"] == "g"
    assert W.choose_split_facet([parts[2]]) is None and W.choose_split_facet(None) is None


def test_body_is_a_separate_request_and_a_closed_posting_says_so():
    path = "/job/Toronto/Software-Intern_R1"
    detail = "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Careers" + path
    http = FakeHttp({detail: {"jobPostingInfo": {"jobDescription": "<p>Build things</p>", "canApply": True}}})
    assert W.fetch_body(BOARD, {"ref": path}, http) == ("Build things", True)
    http = FakeHttp({detail: {"jobPostingInfo": {"canApply": False}}})
    assert W.fetch_body(BOARD, {"ref": path}, http) == ("", False)
    assert W.fetch_body(BOARD, {"ref": path}, FakeHttp({})) == ("", False)          # 404 is closed
    import pytest
    with pytest.raises(FetchError):
        W.fetch_body(BOARD, {"ref": path}, FakeHttp({detail: FetchError("x", "http500", 500)}))


def test_public_link_parsing():
    board, path = W.parse_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/Santa-Clara/Intern_JR1?x=1")
    assert board == {"ats": "workday", "token": "nvidia", "wd": "wd5", "site": "NVIDIAExternalCareerSite"}
    assert path == "/job/Santa-Clara/Intern_JR1"
    assert W.parse_url("https://example.com/job/1") is None
