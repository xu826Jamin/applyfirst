"""Each reader turns its system's answer into plain postings, offline."""
import pytest
from test_sources_fakes import FakeHttp

from applyfirst.sources import fetchers as F
from applyfirst.sources.net import FetchError
from applyfirst.sources.util import parse_age_text, parse_posted, strip_html


def run(ats, token, routes, **board):
    http = FakeHttp(routes)
    b = {"ats": ats, "token": token, "company": "Acme", **board}
    return F.FETCHERS[ats](b, F.Ctx(http=http)), http


def test_greenhouse_uses_first_published_and_unescapes_content():
    res, _ = run("greenhouse", "acme", {
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": {"jobs": [{
            "id": 11, "title": "Software Intern", "absolute_url": "https://boards.greenhouse.io/acme/jobs/11",
            "location": {"name": "Toronto, ON"}, "updated_at": "2026-11-10T10:00:00-05:00",
            "first_published": "2026-10-01T09:00:00-04:00",
            "content": "&lt;p&gt;Build &amp;amp; ship things&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;"}]}})
    p = res.postings[0]
    assert p["job_id"] == "11" and p["location"] == "Toronto, ON"
    assert p["posted_at"].startswith("2026-10-01")      # when it went up, not when it was last edited
    assert "Build & ship things" in p["description"] and "Python" in p["description"] and "<" not in p["description"]
    assert res.complete


def test_lever_description_includes_the_requirement_lists():
    res, _ = run("lever", "acme", {"https://api.lever.co/v0/postings/acme?mode=json": [{
        "id": "abc", "text": "Co-op Developer", "hostedUrl": "https://jobs.lever.co/acme/abc",
        "applyUrl": "https://jobs.lever.co/acme/abc/apply", "createdAt": 1760000000000,
        "categories": {"location": "Montreal, QC", "allLocations": ["Montreal, QC", "Remote"]},
        "descriptionPlain": "About the role.", "lists": [{"text": "Requirements", "content": "<li>Know Python</li>"}],
        "additionalPlain": "We value everyone.", "workplaceType": "hybrid", "country": "CA"}]})
    p = res.postings[0]
    assert "Requirements" in p["description"] and "Know Python" in p["description"]
    assert "About the role." in p["description"] and "We value everyone." in p["description"]
    assert p["location"] == "Montreal, QC; Remote" and p["country_hint"] == "CA"
    assert p["posted_at"].startswith("2025-10-0")        # epoch milliseconds read as a date
    assert p["apply_url"].endswith("/apply")


def test_ashby_skips_unlisted_and_joins_locations():
    res, _ = run("ashby", "acme", {
        "https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=false": {"jobs": [
            {"id": "1", "title": "New Grad Engineer", "location": "Toronto", "secondaryLocations": [{"location": "Remote - Canada"}],
             "jobUrl": "https://jobs.ashbyhq.com/acme/1", "publishedAt": "2026-11-01T00:00:00.000+00:00",
             "descriptionPlain": "Hello", "isRemote": False},
            {"id": "2", "title": "Hidden", "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/acme/2"}]}})
    assert [p["job_id"] for p in res.postings] == ["1"]
    assert res.postings[0]["location"] == "Toronto; Remote - Canada"


def test_smartrecruiters_pages_and_marks_a_long_board_incomplete():
    def page(url, _):
        offset = int(url.split("offset=")[1])
        return {"totalFound": 5000, "content": [
            {"id": str(offset + i), "name": "Intern", "location": {"city": "Ottawa", "country": "ca"},
             "releasedDate": "2026-11-01T00:00:00Z"} for i in range(100)]}
    res, http = run("smartrecruiters", "acme", {"https://api.smartrecruiters.com/v1/companies/acme/postings?limit=100&offset=*": page})
    assert len(res.postings) == 1000 and not res.complete       # stopped at the page cap, so absence proves nothing
    assert res.postings[0]["country_hint"] == "CA"


def test_smartrecruiters_short_board_is_complete():
    res, _ = run("smartrecruiters", "acme", {
        "https://api.smartrecruiters.com/v1/companies/acme/postings?limit=100&offset=0": {
            "totalFound": 1, "content": [{"id": "9", "name": "Analyst", "location": {"city": "X", "country": "us"}}]}})
    assert res.complete and res.postings[0]["url"] == "https://jobs.smartrecruiters.com/acme/9"


def test_workable_recruitee_bamboohr_breezy_pinpoint():
    res, _ = run("workable", "acme", {"https://apply.workable.com/api/v1/widget/accounts/acme?details=true": {"jobs": [
        {"shortcode": "AB12", "title": "Dev Intern", "city": "Calgary", "state": "Alberta", "country": "Canada",
         "url": "https://apply.workable.com/acme/j/AB12/", "published_on": "2026-11-02", "description": "<p>Hi</p>",
         "telecommuting": True}]}})
    assert res.postings[0]["location"] == "Calgary, Alberta, Canada" and res.postings[0]["workplace"] == "remote"
    res, _ = run("recruitee", "acme", {"https://acme.recruitee.com/api/offers/": {"offers": [
        {"id": 5, "title": "Stage", "careers_url": "https://acme.recruitee.com/o/stage", "city": "Lyon", "country": "France",
         "description": "<b>x</b>", "published_at": "2026-11-03 10:00:00 UTC", "country_code": "FR"}]}})
    assert res.postings[0]["job_id"] == "5" and res.postings[0]["country_hint"] == "FR"
    res, _ = run("bamboohr", "acme", {"https://acme.bamboohr.com/careers/list": {"result": [
        {"id": "7", "jobOpeningName": "Intern", "location": {"city": "Boise", "state": "ID"}, "isRemote": None}]}})
    assert res.postings[0]["url"] == "https://acme.bamboohr.com/careers/7" and res.postings[0]["location"] == "Boise, ID"
    res, _ = run("breezy", "acme", {"https://acme.breezy.hr/json": [
        {"id": "z", "name": "Intern", "url": "https://acme.breezy.hr/p/z", "published_date": "2026-11-04T00:00:00.000Z",
         "location": {"name": "Remote", "is_remote": True, "country": {"name": "Canada"}}}]})
    assert res.postings[0]["workplace"] == "remote" and "Canada" in res.postings[0]["location"]
    res, _ = run("pinpoint", "acme", {"https://acme.pinpointhq.com/postings.json": {"data": [
        {"id": "3", "title": "Grad", "url": "https://acme.pinpointhq.com/en/postings/3", "location": {"city": "Leeds", "province": "England"}}]}})
    assert res.postings[0]["location"] == "Leeds, England"


def test_personio_and_teamtailor_read_xml():
    xml = ("<workzag-jobs><position><id>42</id><office>Berlin</office><name>Werkstudent</name>"
           "<createdAt>2026-11-05T08:00:00+00:00</createdAt><jobDescriptions><jobDescription><name>Tasks</name>"
           "<value>&lt;p&gt;Code&lt;/p&gt;</value></jobDescription></jobDescriptions></position></workzag-jobs>")
    res, _ = run("personio", "acme", {"https://acme.jobs.personio.de/xml": xml})
    p = res.postings[0]
    assert p["url"] == "https://acme.jobs.personio.de/job/42" and "Code" in p["description"] and p["location"] == "Berlin"
    # .de missing, .com present
    res, _ = run("personio", "acme", {"https://acme.jobs.personio.com/xml": xml})
    assert res.postings[0]["url"].startswith("https://acme.jobs.personio.com/")
    rss = ("<rss><channel><item><title>Intern</title><link>https://acme.teamtailor.com/jobs/1-intern</link>"
           "<guid>g1</guid><pubDate>Mon, 03 Nov 2026 10:00:00 +0000</pubDate><description>&lt;p&gt;Hi&lt;/p&gt;</description>"
           "</item></channel></rss>")
    res, _ = run("teamtailor", "acme", {"https://acme.teamtailor.com/jobs.rss": rss})
    assert res.postings[0]["title"] == "Intern" and res.postings[0]["posted_at"].startswith("2026-11-03")


def test_oracle_cloud_reads_requisitions_and_builds_the_public_link():
    res, http = run("oraclecloud", "abcd", {"https://abcd.fa.ocs.oraclecloud.com/hcmRestApi/*": {"items": [{
        "requisitionList": [{"Id": "1234", "Title": "Student Developer", "PrimaryLocation": "Toronto, ON, Canada",
                             "PostedDate": "2026-11-06"}]}]}})
    p = res.postings[0]
    assert p["url"] == "https://abcd.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/1234"
    assert res.complete and "findReqs" in http.calls[0][0]


def test_phenom_is_never_a_whole_board_and_rejects_a_non_phenom_answer():
    res, _ = run("phenom", "jobs.example.com", {"https://jobs.example.com/widgets": {"refineSearch": {"data": {"jobs": [
        {"jobId": "J1", "title": "Intern", "location": "Ottawa, Ontario", "postedDate": "2026-11-07T00:00:00.000+0000"}]}}}})
    assert res.postings[0]["job_id"] == "J1" and not res.complete
    with pytest.raises(FetchError) as e:
        run("phenom", "jobs.example.com", {"https://jobs.example.com/widgets": {"hello": 1}})
    assert e.value.kind == "bad-response"


def test_a_board_that_cannot_be_read_raises_instead_of_returning_empty():
    for ats in ("greenhouse", "lever", "ashby"):
        with pytest.raises(FetchError) as e:
            run(ats, "gone", {})
        assert e.value.kind == "http404"
    with pytest.raises(FetchError) as e:
        run("greenhouse", "x", {"https://boards-api.greenhouse.io/v1/boards/x/jobs?content=true": {"oops": []}})
    assert e.value.kind == "bad-response"


def test_a_token_cannot_rewrite_the_url():
    http = FakeHttp({})
    with pytest.raises(FetchError):
        F.greenhouse({"ats": "greenhouse", "token": "../evil?x=", "company": "x"}, F.Ctx(http=http))
    url = http.calls[0][0]
    assert "/evil" not in url and "?x" not in url and "/../" not in url      # one path part, encoded
    with pytest.raises(FetchError):
        F.recruitee({"ats": "recruitee", "token": "evil.com/x", "company": "x"}, F.Ctx(http=FakeHttp()))


def test_every_seed_board_has_a_reader_and_workday_has_its_site():
    import json
    from pathlib import Path
    import applyfirst.sources as S
    seed = json.loads((Path(S.__file__).parent / "boards.json").read_text(encoding="utf-8"))
    assert len(seed) > 500
    for b in seed:
        assert b["ats"] in F.FETCHERS and b["token"] and b["company"]
        if b["ats"] == "workday":
            assert b.get("site") and b.get("wd")
    # only the fields the readers use: nothing personal rides along in the shipped list
    assert all(set(b) <= {"ats", "token", "company", "site", "wd", "oc_pod"} for b in seed)


# ------------------------------------------------------------------------------------ helpers

def test_parse_posted_shapes():
    assert parse_posted(1760000000) .startswith("2025-10-0")
    assert parse_posted("2026-11-01T00:00:00Z") == "2026-11-01T00:00:00+00:00"
    assert parse_posted("") == "" and parse_posted(None) == "" and parse_posted("garbage") == ""
    assert parse_posted("Posted 30+ Days Ago") == ""         # a lower bound, not a date


def test_workday_relative_dates():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
    assert parse_posted("Posted Today", now).startswith("2026-11-15")
    assert parse_posted("Posted Yesterday", now).startswith("2026-11-14")
    assert parse_posted("Posted 3 Days Ago", now).startswith("2026-11-12")


def test_parse_age_text():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
    assert parse_age_text("24h", now).startswith("2026-11-14T15")
    assert parse_age_text("2d", now).startswith("2026-11-13")
    assert parse_age_text("Just posted", now).startswith("2026-11-15")
    assert parse_age_text("30+ days ago", now) == ""
    assert parse_age_text("", now) == ""


def test_strip_html_keeps_line_breaks_between_blocks():
    assert strip_html("<p>One</p><p>Two &amp; three</p>") == "One\nTwo & three"
