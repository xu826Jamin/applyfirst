"""An install made by an older version keeps working after an update adds columns."""
import sqlite3

from applyfirst import config, store


def test_old_database_gains_new_columns(tmp_home):
    store.reset()
    path = config.path("applyfirst.sqlite")
    path.unlink(missing_ok=True)
    old = sqlite3.connect(path)
    # an "old version" applications table: missing most of today's columns
    old.execute("CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, posting_id TEXT, "
                "company TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    old.execute("INSERT INTO applications (posting_id, company, title, created_at, updated_at) "
                "VALUES ('p1', 'Acme', 'Intern', 'x', 'x')")
    old.commit()
    old.close()

    row = store.one("SELECT status, outcome, notes FROM applications")   # opening runs the upgrade
    assert row == {"status": "queued", "outcome": "", "notes": ""}
    assert store.upgrade(store.db()) == []          # nothing left to add the second time
