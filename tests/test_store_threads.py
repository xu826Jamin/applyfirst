"""The interface reads while a background job writes; that must never error."""
import threading

from applyfirst import store


def test_concurrent_reads_during_background_writes(tmp_home):
    rid = store.start_run("sweep")
    stop = threading.Event()
    errors = []

    def writer():
        con = store.db()
        i = 0
        while not stop.is_set():
            con.execute("INSERT OR REPLACE INTO postings (id, source, company, title, url, first_seen_at) "
                        "VALUES (?,?,?,?,?,?)", (f"x:{i}", "x", "c", "t", "u", store.now()))
            i += 1
            if i % 50 == 0:
                con.commit()
        con.commit()

    def reader():
        for _ in range(400):
            try:
                store.one("SELECT log_file FROM runs WHERE id=?", (rid,))
                store.rows("SELECT COUNT(*) n FROM postings")
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

    w = threading.Thread(target=writer)
    w.start()
    readers = [threading.Thread(target=reader) for _ in range(3)]
    for r in readers:
        r.start()
    for r in readers:
        r.join()
    stop.set()
    w.join()
    assert errors == []
