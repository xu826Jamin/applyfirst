"""Matches show up mid-sweep: a batch of new postings is judged as soon as it is stored."""
from applyfirst import store
from applyfirst.sources.run import _filter_batch


def _add(pid, title, location):
    store.upsert("postings", {"id": pid, "source": "greenhouse", "company": "Acme", "title": title,
                              "location": location, "url": f"https://example.com/{pid}",
                              "first_seen_at": store.now()})


def test_only_the_batch_is_judged(alex):
    _add("a", "Software Engineering Intern", "Toronto, ON")
    _add("b", "Software Engineering Intern", "Toronto, ON")
    _filter_batch("run", ["a"])
    v = {r["id"]: r["verdict"] for r in store.rows("SELECT id, verdict FROM postings")}
    assert v["a"] == "keep"
    assert v["b"] == ""          # not in the batch, untouched until the end-of-sweep pass
