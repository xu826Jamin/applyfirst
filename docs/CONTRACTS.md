# Contracts between packages

The product: find postings the hour they go up, apply first, and show what is actually
getting interviews. Five Python packages, one web interface, one shared store.

Shared pieces (already written, do not change their signatures; additions are fine):

- `applyfirst/config.py`: data home, `load_profile()`, `load_settings()`, `get(settings, "a.b")`,
  `load_secrets()`. Every setting and its default is in `DEFAULT_SETTINGS`. Read settings,
  never hard-code a user preference.
- `applyfirst/store.py` + `applyfirst/schema.sql`: SQLite. `rows`, `one`, `execute`, `upsert`,
  `start_run`, `log`, `finish_run`, `now`. A package needing its own table adds
  `applyfirst/<package>/schema.sql` (CREATE TABLE IF NOT EXISTS only).
- `applyfirst/jobs.py`: `spawn(kind, fn)` runs `fn(run_id) -> summary` in a thread.
- `applyfirst/claude.py`: `run(prompt, run_id, browser=..., json_schema=...) -> Result`
  (ok, text, structured, cost_usd, turns, error). Headless Claude Code.
- `applyfirst/server.py`: mounts `applyfirst/<package>/api.py:router` at `/api/<package>`.

Rules for every package:

- Tests in `tests/test_<package>*.py`, pytest, offline (no network, no Claude). Use the
  `tmp_home` fixture in `tests/conftest.py`.
- Never write user data inside the repo. No personal data of any real person in code,
  tests or fixtures: use the fictional "Alex Rivera" profile in `tests/conftest.py`.
- A retrieval failure stays empty and is counted, never filled in with a guess.
- Plain-language reasons and summaries: they are shown to the user.

---

## sources: find postings

`applyfirst/sources/__init__.py`

- `sweep(run_id: str) -> str`: polls every source enabled in `settings.sources`, writes
  `postings` rows (id, source, company, title, location, remote, country, url, apply_url,
  ats, description, posted_at, first_seen_at, deadline if stated, fingerprint, duplicate_of,
  raw), marks postings that disappeared from a board as `alive=0`, then calls
  `applyfirst.filters.evaluate_all(run_id)` if importable. Returns e.g.
  "Checked 4,512 boards, 37 new postings, 12 match your settings."
- `add_manual(url: str) -> dict`: a posting from a pasted link (fetch it if the ATS is known,
  otherwise store url + title from the page).
- Board list: `applyfirst/sources/boards.json` (ats, token, company). `discover(run_id)` grows it.

`applyfirst/sources/api.py` routes:
- `POST /sweep` -> `{run_id}`; `POST /manual {url}` -> posting; `GET /boards` -> counts by ATS.

## filters: what to keep and in what order

`applyfirst/filters/__init__.py`

- `classify(posting: dict) -> dict`: fills level, field, term_months, deadline, country/region
  from title + description + location when empty.
- `evaluate(posting: dict, settings: dict, profile: dict) -> tuple[str, list[str]]`:
  ("keep" | "skip", plain-language reasons).
- `evaluate_all(run_id: str | None = None) -> dict`: classify + evaluate every live,
  non-duplicate posting; writes verdict and verdict_reasons; returns counts.
- `order(postings: list[dict], settings: dict) -> list[dict]`: by `queue.order_by`, then
  `queue.then_by` (newest | deadline | company | match).
- `queue(settings, view="kept", limit=100) -> list[dict]`: ordered postings for a view:
  kept (verdict keep, no user action), approved, skipped, all.

`applyfirst/filters/api.py` routes:
- `GET /queue?view=kept&limit=100`; `POST /postings/{id}/action {action: approve|skip|reset}`;
  `POST /reevaluate`; `GET /postings/{id}` (posting + reasons).

## resume: the experience bank and resume files

`applyfirst/resume/__init__.py`

- `import_pdf(path: str, run_id=None) -> list[dict]`: text from the PDF, structured into
  `experience` rows (unconfirmed) with Claude; a plain heuristic parser when Claude is absent.
- `build(role_type: str | None = None, posting: dict | None = None) -> str`: picks lines from
  the confirmed experience bank, renders one page, returns the PDF path. File name
  `First_Last_Resume.pdf` (a tailored variant adds company and role).
- `verify(pdf_path: str) -> list[str]`: problems; every line must trace to the bank.
- `resume_for(posting: dict, settings: dict) -> str`: honours `apply.resume_tailoring`.
- `cover_letter(posting: dict, run_id=None) -> str | None`: None when the posting body is empty.

`applyfirst/resume/api.py` routes:
- `POST /import` (multipart file) -> rows; `GET /experience`; `PUT /experience/{id}`;
  `POST /experience` (new row); `DELETE /experience/{id}`; `POST /experience/confirm-all`;
  `GET /preview?role_type=` -> PDF; `GET /files` ; `GET /files/{name}`.

## apply: fill and submit

`applyfirst/apply/__init__.py`

- `apply_queue(run_id: str, limit: int | None = None) -> str`: approved postings (plus kept
  ones in auto mode, after `apply.review_first`), within `queue.daily_limit`, in queue order.
  For each: create the `applications` row, pick the resume, build the brief (profile facts,
  learned answers, settings), run Claude Code with the browser, record outcome and cost.
  Review mode fills and stops before the final submit with the tab left open
  (`ready-to-submit`); auto mode submits and reads the confirmation back off the page.
  Unknown required questions go to `answers` with `pending=1` and the application becomes
  `needs-you`. Sign-in walls and CAPTCHAs also become `needs-you` with the reason.
- `standard_answers(profile, settings) -> dict`: the answers derived from the profile.
- `learn(question: str, answer: str, source="user")`.
- `applyfirst/apply/workday_fill.js`: the one-call Workday filler.

`applyfirst/apply/api.py` routes:
- `POST /run {limit}` -> `{run_id}`; `GET /applications?status=`;
  `POST /applications/{id}/status {status}` (e.g. user clicked submit themselves);
  `GET /answers?pending=1`; `PUT /answers/{key} {answer}`; `GET /cost` (average per application).

## tracker: replies and what is working

`applyfirst/tracker/__init__.py`

- `sync(run_id: str) -> str`: IMAP (settings.tracker.email + secret `imap_password`), last 35
  days on first run then since last sync; classify each message (confirmation, rejection,
  assessment, interview, offer, other); match to an application by company and role;
  confirmations mark `submitted`; outcomes set `outcome`, `outcome_at`, `outcome_source=email`.
  Never sends, moves, flags or deletes mail.
- `classify(subject: str, body: str, sender: str) -> str`.
- `stats() -> dict`: applications, responses, interviews and the interview rate, broken down
  by source, resume variant, field, and posting age when applied (hours since first seen),
  plus a weekly series. Small samples are labelled as such.

`applyfirst/tracker/api.py` routes:
- `POST /sync` -> `{run_id}`; `GET /stats`; `POST /applications/{id}/outcome {outcome}`.

## web: the interface

`web/index.html`, `web/app.js`, `web/styles.css`, served at `/` and `/static/`. No build
step. Screens: Setup (resume import, profile, targets), Jobs (queue, approve/skip, why kept
or skipped), Applications (status board, needs-you list, outcomes), Answers (learned and
pending questions), Insights (stats), Settings (every setting, warnings shown inline),
Activity (runs and logs). Core routes: `GET/PUT /api/profile`, `GET/PUT /api/settings`,
`GET /api/status`, `GET /api/runs`, `GET /api/runs/{id}/log`, `PUT /api/secrets/{key}`.
