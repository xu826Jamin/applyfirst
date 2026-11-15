-- Core tables. Every package reads and writes these through store.py.
-- A package that needs its own table puts it in applyfirst/<package>/schema.sql;
-- store.init() runs every such file after this one. Never edit another package's file.

CREATE TABLE IF NOT EXISTS postings (
  id            TEXT PRIMARY KEY,         -- stable: source + ':' + source-specific id
  source        TEXT NOT NULL,            -- greenhouse | lever | ashby | workday | ... | indeed | manual
  company       TEXT NOT NULL,
  title         TEXT NOT NULL,
  location      TEXT DEFAULT '',
  remote        INTEGER DEFAULT 0,        -- 1 if fully remote
  country       TEXT DEFAULT '',          -- ISO code when known
  url           TEXT NOT NULL,            -- the posting page
  apply_url     TEXT DEFAULT '',          -- the application form, when different
  ats           TEXT DEFAULT '',          -- the system the form runs on
  description   TEXT DEFAULT '',          -- plain text body; '' means not retrieved (never guessed)
  posted_at     TEXT DEFAULT '',          -- ISO timestamp from the source; '' if unknown
  first_seen_at TEXT NOT NULL,            -- when we first saw it
  deadline      TEXT DEFAULT '',          -- ISO date if the posting states one
  level         TEXT DEFAULT '',          -- internship | co-op | new-grad | entry | mid | senior | ''
  field         TEXT DEFAULT '',
  term_months   INTEGER,
  fingerprint   TEXT DEFAULT '',          -- content hash for cross-board duplicates
  duplicate_of  TEXT DEFAULT '',          -- id of the posting this repeats
  alive         INTEGER DEFAULT 1,        -- 0 once confirmed closed
  verdict       TEXT DEFAULT '',          -- keep | skip  (filters package)
  verdict_reasons TEXT DEFAULT '[]',      -- JSON list of plain-language reasons
  user_action   TEXT DEFAULT '',          -- '' | approved | skipped  (set in the interface)
  raw           TEXT DEFAULT '{}'         -- JSON from the source, for debugging
);
CREATE INDEX IF NOT EXISTS postings_seen ON postings(first_seen_at);
CREATE INDEX IF NOT EXISTS postings_verdict ON postings(verdict);

CREATE TABLE IF NOT EXISTS applications (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  posting_id    TEXT,
  company       TEXT NOT NULL,
  title         TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'queued',
      -- queued | filling | needs-you | ready-to-submit | submitted | failed
  needs_you     TEXT DEFAULT '',          -- why it stopped: sign-in, captcha, question, review
  resume_file   TEXT DEFAULT '',
  cover_letter_file TEXT DEFAULT '',
  submitted_at  TEXT DEFAULT '',
  outcome       TEXT DEFAULT '',          -- '' | rejected | assessment | interview | offer | withdrawn
  outcome_at    TEXT DEFAULT '',
  outcome_source TEXT DEFAULT '',         -- email | manual
  run_id        TEXT DEFAULT '',
  notes         TEXT DEFAULT '',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS applications_posting ON applications(posting_id);

-- Form questions the system has learned answers to. Asked once, reused after.
CREATE TABLE IF NOT EXISTS answers (
  key           TEXT PRIMARY KEY,         -- normalized question text
  question      TEXT NOT NULL,            -- as first seen
  answer        TEXT NOT NULL DEFAULT '',
  source        TEXT NOT NULL DEFAULT 'learned',  -- profile | learned | user
  pending       INTEGER NOT NULL DEFAULT 0,       -- 1 = waiting for the user to answer
  uses          INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT NOT NULL
);

-- The user's real experience. Resumes are assembled from these lines only.
CREATE TABLE IF NOT EXISTS experience (
  id            TEXT PRIMARY KEY,         -- e.g. E1, E1.b2
  parent_id     TEXT DEFAULT '',          -- '' for an entry, entry id for a bullet
  section       TEXT NOT NULL,            -- experience | projects | education | skills | other
  title         TEXT DEFAULT '',          -- role or project name (entries)
  org           TEXT DEFAULT '',
  dates         TEXT DEFAULT '',
  text          TEXT DEFAULT '',          -- the bullet (bullets)
  tags          TEXT DEFAULT '[]',        -- JSON list: skills, tools, role types
  confirmed     INTEGER NOT NULL DEFAULT 0,  -- 1 once the user has approved it
  position      INTEGER NOT NULL DEFAULT 0
);

-- Every unattended or button-started job: sweep, apply batch, mail sync.
CREATE TABLE IF NOT EXISTS runs (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,            -- sweep | apply | sync | resume
  status        TEXT NOT NULL,            -- running | done | failed
  started_at    TEXT NOT NULL,
  finished_at   TEXT DEFAULT '',
  summary       TEXT DEFAULT '',          -- one plain-language line
  log_file      TEXT DEFAULT ''
);
