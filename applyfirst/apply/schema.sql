-- Tables owned by the apply package (CREATE TABLE IF NOT EXISTS only).

-- One row per Claude run on an application. Cost per application is the sum of its rows.
CREATE TABLE IF NOT EXISTS application_costs (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id INTEGER NOT NULL,
  run_id         TEXT DEFAULT '',
  mode           TEXT DEFAULT '',          -- review | auto
  cost_usd       REAL NOT NULL DEFAULT 0,
  turns          INTEGER DEFAULT 0,
  outcome_status TEXT DEFAULT '',          -- the status that run ended in
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS application_costs_app ON application_costs(application_id);

-- Required questions an application stopped on, with the form's own type and options.
CREATE TABLE IF NOT EXISTS application_questions (
  application_id INTEGER NOT NULL,
  key            TEXT NOT NULL,            -- answers.key
  question       TEXT NOT NULL,
  type           TEXT DEFAULT '',
  options        TEXT DEFAULT '[]',        -- JSON list
  created_at     TEXT NOT NULL,
  PRIMARY KEY (application_id, key)
);
