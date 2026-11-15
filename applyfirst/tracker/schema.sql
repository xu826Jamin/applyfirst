-- tracker package tables. CREATE TABLE IF NOT EXISTS only.

-- Small key/value state: the sync high-water mark and the last result.
CREATE TABLE IF NOT EXISTS tracker_state (
  key           TEXT PRIMARY KEY,
  value         TEXT NOT NULL DEFAULT ''
);

-- One row per application-related email. Subject, sender, date and the class we gave it.
-- The body is never stored.
CREATE TABLE IF NOT EXISTS tracker_messages (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id    TEXT NOT NULL UNIQUE,     -- the Message-ID header (or a hash when absent)
  thread_id     TEXT DEFAULT '',
  subject       TEXT DEFAULT '',
  sender        TEXT DEFAULT '',
  date          TEXT DEFAULT '',          -- ISO timestamp (UTC) of the message
  class         TEXT NOT NULL DEFAULT 'other',
      -- confirmation | rejection | assessment | interview | offer | other
  application_id INTEGER,                 -- the matched application, NULL when unmatched
  match_note    TEXT DEFAULT '',          -- plain-language why it matched or did not
  candidates    TEXT DEFAULT '[]',        -- JSON list of application ids it could be
  needs_match   INTEGER NOT NULL DEFAULT 0, -- 1 = a real reply nobody could place; the user resolves it
  run_id        TEXT DEFAULT '',
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tracker_messages_app ON tracker_messages(application_id);
CREATE INDEX IF NOT EXISTS tracker_messages_needs ON tracker_messages(needs_match);

-- Sender domains learned per employer, so an anonymous "thanks for applying" from a domain
-- already seen on a named mail is placed too.
CREATE TABLE IF NOT EXISTS tracker_domains (
  domain        TEXT PRIMARY KEY,
  company_key   TEXT NOT NULL
);
