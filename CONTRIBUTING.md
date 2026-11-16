# Contributing to applyfirst

Thank you for helping. The most useful fix is usually small: a job site changed its form or its
data, and one reader needs to follow. This page shows how to find your way around, run the checks,
and send a change.

User guides live in [docs](docs): [Getting started](docs/GETTING_STARTED.md),
[Email](docs/EMAIL.md), [Daily runs](docs/DAILY.md) and
[Troubleshooting](docs/TROUBLESHOOTING.md). Security reports go through [SECURITY.md](SECURITY.md).

## How the code is organised

applyfirst is a local Python app: a FastAPI server, a plain JavaScript interface with no build
step, and a SQLite database in the user's data folder (`~/.applyfirst`, or wherever
`APPLYFIRST_HOME` points).

| Folder | What it does |
| --- | --- |
| `applyfirst/sources/` | Find postings: one reader per job-board system, board discovery, pasted links |
| `applyfirst/filters/` | Decide what to keep and in what order, with a plain reason for every verdict |
| `applyfirst/resume/` | Import a resume, keep the experience bank, build resumes from confirmed lines |
| `applyfirst/apply/` | Fill and submit applications with Claude Code in a Chrome window (`own_window.py`) |
| `applyfirst/tracker/` | Read replies over IMAP (read only) and compute what gets interviews |
| `applyfirst/web/` | The interface: `app.js`, `setup.js`, `settings.js`, `lib.js` |
| `applyfirst/config.py` | Every setting and its default, in `DEFAULT_SETTINGS` |

[docs/CONTRACTS.md](docs/CONTRACTS.md) is the map. It lists what each package must provide, the
routes it mounts, and the rules every package follows. Read it before changing how packages talk
to each other. A few rules worth repeating:

- Read settings with `config.get`; never hard-code a user preference.
- Never write user data inside the repo. Never put a real person's data in code, tests or
  fixtures. Tests use the fictional "Alex Rivera" profile in `tests/conftest.py`.
- When a retrieval fails, leave the value empty and count the failure. Never fill it with a guess.
- The background Claude is locked down on purpose (browser tools only). Do not widen what
  `applyfirst/claude.py` allows without raising it in an issue first.

## Run the tests

You need Python 3.10 or newer.

```
git clone https://github.com/xu826Jamin/applyfirst
cd applyfirst
pip install -e ".[dev]"
pytest
```

The tests are all offline: no network and no Claude. They run against a fresh temporary data
folder (the `tmp_home` fixture), so they never touch your own `~/.applyfirst`. Continuous
integration runs them on Linux, Windows and macOS with Python 3.10 and 3.12, so a change should
pass on all of them. Mind path separators and line endings.

## The live end-to-end check

The tests above cannot tell you whether real job boards still answer the way the readers expect, or
whether a real form still fills. The end-to-end script can. It starts a real server on an empty
data folder and walks a new user's path: setup, a real search, filtering, ordering, building a resume,
answers, outcomes and every screen.

```
python tests/e2e/run_e2e.py
```

It needs the network, Claude Code signed in, and Chrome or Edge installed (it renders the test
resume and checks every screen in a headless browser). The test person is fictional.

To also fill one real application form, in review mode, add `--apply`:

```
python tests/e2e/run_e2e.py --apply
```

Claude fills the form and leaves it unsubmitted. Nothing is sent to the employer. This run uses the
applyfirst Chrome window (reached through `npx`), so it also needs Node.js. Add `--discover`
to run full board discovery on the first search. The script exits 0 only when every check passed.

## Fix or add a job-site reader

A reader turns one job-board system's answer into plain postings. Every reader lives in
`applyfirst/sources/fetchers.py`, and the `FETCHERS` registry at the bottom maps the system's name to
its function.

**To fix a reader**, find it by name (`greenhouse`, `lever`, `ashby`, `workday` and so on), see what
the site returns now, and change the function to match.

**To add one**:

1. Write a function `def mysite(board, ctx) -> FetchResult` in `fetchers.py`. A `board` is
   `{"ats": ..., "token": ..., "company": ...}`. Fetch with `ctx.http.json(url)` (or `.text`, or
   `.post_json`), and build each posting with `_posting(job_id, title, url, location=...,
   posted_at=..., description=...)`. Use `parse_posted` for dates and `strip_html` for text.
   Quote board tokens with `_q(token)` so one can never rewrite a URL path.
2. Raise `FetchError` when you cannot read the board. A reader must never return an empty list to
   mean "I could not read it": the sweep would treat every posting on that board as gone. Return
   `FetchResult(postings, complete=False)` only when the list is a slice of the board.
3. If the list has no posting text, also write a body reader and register it in `BODY_FETCHERS`;
   the sweep calls it only for new postings.
4. Register it: add `"mysite": mysite` to `FETCHERS`.
5. Teach `applyfirst/sources/detect.py` the site's link format, so a pasted link finds the right
   board, and add boards for it to `applyfirst/sources/boards.json`.
6. Add an offline test (next section).

Run `python tests/e2e/run_e2e.py` once to see the reader work on a live board.

### The offline test

Every reader has a test in `tests/test_sources_fetchers.py` that feeds it a **recorded sample**: a
small, trimmed copy of what the site really returned. The `FakeHttp` helper in
`tests/test_sources_fakes.py` answers from a table of URL to value, and any URL not in the table is a
404, so a test can never quietly reach the web. A test looks like this:

```python
def test_mysite_reads_title_location_and_date():
    res, _ = run("mysite", "acme", {
        "https://api.mysite.example/acme/jobs": {"jobs": [{
            "id": 7, "title": "Software Intern", "url": "https://mysite.example/acme/7",
            "location": "Toronto, ON", "published": "2026-10-01T09:00:00Z"}]}})
    p = res.postings[0]
    assert p["title"] == "Software Intern" and p["location"] == "Toronto, ON"
    assert p["posted_at"].startswith("2026-10-01")
    assert res.complete
```

Trim the sample to the fields the reader uses and change company names to fictional ones. Never
put a real person's details in a fixture. Add a second test for the failure case: when the site
returns something unexpected, the reader raises `FetchError`.

## Writing style for text users read

Anything a user sees, in the interface, the guides, the README or an error message, follows the
same rules:

- **Plain words.** Write what the person gets and what to do next. Say "search", not "sweep";
  say "needs you", not "blocked on user input".
- **Use the app's real labels** in bold: **Find jobs**, **Apply to approved**, **Needs you**,
  **I submitted it**. Check the spelling against the interface.
- **Lead with the useful part**, then the step. Keep sentences short.
- **No em dashes.** Use a period, comma or colon.
- **Say the limit plainly when it saves the reader time.** Nothing false is ever said.
- Reasons and summaries shown to users are plain sentences, not log lines or code names.

## Licence of contributions

applyfirst is licensed under the AGPL v3.0 or later. By sending a pull request you agree that your contribution is licensed under those same terms, and that the maintainer may also license it under other terms, for example for a hosted version of applyfirst.

## Sending a change

1. Fork the repo and make your change on a branch.
2. Run `pytest`. Run the end-to-end check if you touched a reader or the apply step.
3. Open a pull request that says what changed and why. For a reader, say which site and what you
   saw it return.

Found something broken but not sure how to fix it? Open an issue. The templates ask for the right
details: a bug report, a broken job site, or a feature request.
