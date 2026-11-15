"""A Workday term search stops paging once relevance runs out, instead of reading the whole board."""
from applyfirst.sources import workday


class FakeHttp:
    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def post_json(self, url, body):
        i = body["offset"] // workday.PAGE
        self.calls += 1
        posts = self.pages[i] if i < len(self.pages) else []
        return {"total": 2000, "facets": [], "jobPostings": posts}


def page(title):
    return [{"title": title, "externalPath": f"/job/{title}-{n}"} for n in range(workday.PAGE)]


def test_term_search_stops_after_two_irrelevant_pages():
    pages = [page("Software Intern"), page("Senior Accountant"), page("Store Manager")] + [page("Analyst")] * 97
    http = FakeHttp(pages)
    posts, total, facets, n = workday._paginate(http, "u", "intern", {}, workday.MAX_PAGES)
    assert http.calls == 3
    assert len(posts) == 3 * workday.PAGE


def test_relevant_page_resets_the_count():
    pages = [page("Intern"), page("Manager"), page("Co-op Student"), page("Director"), page("Director")]
    http = FakeHttp(pages + [page("VP")] * 10)
    workday._paginate(http, "u", "intern", {}, workday.MAX_PAGES)
    assert http.calls == 5


def test_whole_board_read_without_a_term():
    pages = [page("Manager")] * 4 + [[]]
    http = FakeHttp(pages)
    posts, *_ = workday._paginate(http, "u", "", {}, workday.MAX_PAGES)
    assert len(posts) == 4 * workday.PAGE
