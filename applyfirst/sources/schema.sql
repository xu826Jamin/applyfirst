-- Sources package tables. The shared `postings` table lives in the core schema.

-- Which board each posting was read from, and when a sweep last saw it there. A posting that a
-- fully read board no longer lists is closed.
CREATE TABLE IF NOT EXISTS posting_boards (
  posting_id    TEXT PRIMARY KEY,
  board_key     TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS posting_boards_board ON posting_boards(board_key);

-- How each board did the last time it was read, so a board that keeps failing is visible.
CREATE TABLE IF NOT EXISTS boards_state (
  board_key     TEXT PRIMARY KEY,
  ats           TEXT NOT NULL,
  token         TEXT NOT NULL,
  company       TEXT DEFAULT '',
  last_checked  TEXT DEFAULT '',
  last_status   TEXT DEFAULT '',          -- ok | the failure kind
  last_count    INTEGER DEFAULT 0,
  failures      INTEGER DEFAULT 0         -- failures in a row
);

-- When a posting that has no board to disappear from (Indeed, an email alert, a pasted link) was
-- last looked at, so each sweep spends its few page checks on the ones not looked at lately.
CREATE TABLE IF NOT EXISTS liveness_checks (
  posting_id    TEXT PRIMARY KEY,
  checked_at    TEXT NOT NULL,
  result        TEXT NOT NULL             -- live | dead | unknown
);
