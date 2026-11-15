"""End-to-end check of the whole product, driven through the same HTTP API the interface uses.

It starts a real server on a fresh, empty data home and walks a new user's path:

  setup      empty status, resume PDF import (Claude), confirm, profile, settings
  find       a real sweep of live company boards, postings stored with freshness data
  filter     every kept posting obeys the settings; every skipped one says why
  order      newest, deadline and company orders hold
  resume     a one-page PDF builds from the confirmed bank and passes the line check
  apply      one real posting filled by Claude in review mode, never submitted (opt-in)
  answers    pending questions can be answered once and are stored
  replies    no inbox configured is reported plainly; a manual outcome shows in Insights
  interface  every screen renders in a headless browser with no error text
  cli        the command line runs

Usage (from the repo root):
  python tests/e2e/run_e2e.py                    # everything except a live form fill
  python tests/e2e/run_e2e.py --apply            # also fill one real form (review mode)
  python tests/e2e/run_e2e.py --discover         # first sweep also runs full board discovery

Network and Claude Code are required. The test person is fictional (Alex Rivera). In --apply
mode the form is filled and left unsubmitted; nothing is sent to the employer.
Exit code 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable

ALEX_PROFILE = {
    "name": {"first": "Alex", "last": "Rivera", "preferred": ""},
    "email": "alex.rivera@example.com",
    "phone": "555-0100",
    "location": {"city": "Toronto", "region": "Ontario", "country": "CA", "postal_code": ""},
    "links": {"linkedin": "", "github": "https://github.com/example", "portfolio": "", "other": []},
    "education": [{"school": "Example University", "degree": "BEng", "field": "Computer Engineering",
                   "start": "2024-09", "end": "2028-04", "gpa": "", "gpa_scale": "", "current": True}],
    "work_authorization": {"CA": {"authorized": True, "needs_sponsorship": False}},
    "citizenship": ["CA"],
    "languages": [{"language": "English", "level": "Native"}],
    "availability": {"earliest_start": "2027-05-01", "term_months": [4, 8, 12, 16], "willing_to_relocate": True},
    "salary": {"currency": "CAD", "hourly_min": 25, "annual_min": None},
    "demographics": {"gender": "", "pronouns": "", "ethnicity": "", "disability": "", "veteran": ""},
}

BANK = [
    ("experience", "Software Developer Intern", "Northwind Labs", "May 2025 - Aug 2025", [
        "Built a Python service that cut report generation time from 40 minutes to 6 minutes for 12 analysts",
        "Wrote 85 automated tests in pytest, raising coverage of the billing module from 41% to 88%",
        "Migrated three internal tools from cron scripts to a FastAPI app with a React dashboard"]),
    ("projects", "Transit Tracker", "", "2024", [
        "Built a web app showing live bus arrivals for 300 stops using the city's open GTFS feed",
        "Served 1,200 monthly users with a Flask backend and Postgres, deployed on Fly.io"]),
]

# --------------------------------------------------------------------------- reporting

results: list[tuple[str, str, bool, str]] = []


def check(area: str, name: str, ok: bool, detail: str = "") -> bool:
    results.append((area, name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {area}: {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return bool(ok)


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


# --------------------------------------------------------------------------- http

BASE = ""


def call(method: str, path: str, body=None, raw: bool = False, timeout: int = 600, files=None):
    url = BASE + path
    headers = {}
    data = None
    if files:
        boundary = "----applyfirst-e2e"
        name, filename, content = files
        data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload or b"null"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(txt)
        except json.JSONDecodeError:
            return e.code, txt


def wait_run(run_id: str, limit: int) -> dict:
    t0 = time.time()
    last = ""
    while time.time() - t0 < limit:
        _, runs = call("GET", "/api/runs?limit=50")
        run = next((r for r in runs if r["id"] == run_id), None)
        if run and run["status"] != "running":
            return run
        _, log = call("GET", f"/api/runs/{run_id}/log", raw=True)
        line = (log.decode(errors="replace").strip().splitlines() or [""])[-1][26:120]
        if line and line != last:
            print(f"     ... {line}", flush=True)
            last = line
        time.sleep(10)
    return {"status": "timeout", "summary": f"still running after {limit} s"}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def find_chrome() -> str | None:
    for c in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "google-chrome", "chromium", "chromium-browser", "microsoft-edge"]:
        p = shutil.which(c) or (c if os.path.exists(c) else None)
        if p:
            return p
    return None


# --------------------------------------------------------------------------- fixtures


def make_resume_pdf(workdir: Path) -> Path | None:
    """Build Alex's resume with the product itself, in a separate throwaway home."""
    home = workdir / "pdf-home"
    home.mkdir()
    code = f"""
import os, sys, json
os.environ['APPLYFIRST_HOME'] = {str(home)!r}
sys.path.insert(0, {str(ROOT)!r})
from applyfirst import config
from applyfirst.resume import bank, builder
config.save_profile(json.loads({json.dumps(json.dumps(ALEX_PROFILE))}))
for section, title, org, dates, bullets in json.loads({json.dumps(json.dumps(BANK))}):
    e = bank.add({{'section': section, 'title': title, 'org': org, 'dates': dates, 'confirmed': 1}})
    for t in bullets:
        bank.add({{'section': section, 'parent_id': e['id'], 'text': t, 'confirmed': 1}})
bank.add({{'section': 'education', 'title': 'BEng, Computer Engineering', 'org': 'Example University', 'dates': '2024 - 2028', 'confirmed': 1}})
bank.add({{'section': 'skills', 'title': 'Languages', 'text': 'Python, JavaScript, SQL', 'confirmed': 1}})
print(builder.build('software'))
"""
    p = subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    out = (p.stdout.strip().splitlines() or [""])[-1]
    return Path(out) if out.endswith(".pdf") and Path(out).exists() else None


# --------------------------------------------------------------------------- steps


def step_setup(pdf: Path | None) -> None:
    section("Setup")
    code, st = call("GET", "/api/status")
    check("setup", "fresh install reports not set up", code == 200 and st.get("set_up") is False)

    if pdf is None:
        check("setup", "test resume PDF built", False, "no Chrome/Edge to render it")
    else:
        t = time.time()
        code, rows = call("POST", "/api/resume/import", files=("file", "Alex_Rivera_Resume.pdf", pdf.read_bytes()))
        ok = code == 200 and isinstance(rows, list)
        bullets = [r for r in rows if r.get("parent_id")] if ok else []
        check("setup", "resume PDF imports into the experience bank", ok and len(bullets) >= 5,
              f"{len(rows) if ok else code} rows, {len(bullets)} bullets, {time.time() - t:.0f} s")
        if ok:
            check("setup", "imported rows wait for the user to confirm", all(not r.get("confirmed") for r in rows))
            texts = " ".join(r.get("text", "") for r in rows)
            check("setup", "import keeps the numbers exactly", "40 minutes to 6 minutes" in texts and "41% to 88%" in texts)
    code, res = call("POST", "/api/resume/experience/confirm-all", {})
    check("setup", "confirm all", code == 200)

    code, _ = call("PUT", "/api/profile", ALEX_PROFILE)
    check("setup", "profile saves", code == 200)
    code, st = call("GET", "/api/status")
    check("setup", "status now reports set up", st.get("set_up") is True)

    code, s = call("GET", "/api/settings")
    s = s["settings"]
    s["search"].update({"countries": ["CA"], "regions": ["Ontario"], "remote": "include",
                        "levels": ["internship", "co-op", "new-grad"], "fields": ["software", "hardware", "data-ml"]})
    s["queue"].update({"order_by": "newest", "then_by": "deadline", "daily_limit": 1})
    s["apply"].update({"mode": "review", "browser": "playwright"})
    code, saved = call("PUT", "/api/settings", s)
    check("setup", "settings save and read back", code == 200 and saved["settings"]["search"]["regions"] == ["Ontario"])
    check("setup", "warnings ship with settings", "sources.linkedin" in saved.get("warnings", {}))


def step_find(home: Path, discover: bool) -> None:
    section("Find postings (live)")
    if not discover:
        (home / "discovery.json").write_text(json.dumps({"skipped_by": "e2e"}), encoding="utf-8")
    code, r = call("POST", "/api/sources/sweep", {})
    if not check("find", "sweep starts", code == 200 and "run_id" in r, str(r)[:120]):
        return
    t = time.time()
    run = wait_run(r["run_id"], 3600 if discover else 1500)
    check("find", "sweep finishes", run["status"] == "done", f"{time.time() - t:.0f} s: {run.get('summary', '')[:200]}")
    code, boards = call("GET", "/api/sources/boards")
    check("find", "board list loaded", code == 200 and sum(boards.values()) > 500, f"{sum(boards.values())} boards")
    code, st = call("GET", "/api/status")
    check("find", "postings stored", st.get("postings", 0) > 100, f"{st.get('postings')} live postings")
    check("find", "some postings match the settings", st.get("kept", 0) > 0, f"{st.get('kept')} kept")


def step_filter() -> list[dict]:
    section("Filter")
    code, q = call("GET", "/api/filters/queue?view=kept&limit=500")
    kept = q.get("postings", []) if code == 200 else []
    check("filter", "queue returns kept postings", code == 200 and len(kept) > 0, f"{len(kept)}")
    bad_place, bad_level = [], []
    for p in kept:
        full = call("GET", f"/api/filters/postings/{urllib.request.quote(p['id'], safe='')}")[1]
        place_ok = full.get("remote") or (full.get("country") in ("CA", "") and
                                          ("ontario" in (full.get("location", "") + " " + str(full.get("region", ""))).lower()
                                           or any(c in full.get("location", "").lower() for c in
                                                  ["toronto", "ottawa", "waterloo", "kitchener", "mississauga", "markham",
                                                   "hamilton", "london", "oakville", "burlington", "vaughan", "guelph"])))
        if not place_ok:
            bad_place.append(f"{full.get('company')}: {full.get('location')}")
        if full.get("level") and full["level"] not in ("internship", "co-op", "new-grad"):
            bad_level.append(f"{full.get('company')}: {full.get('title')} ({full.get('level')})")
    check("filter", "every kept posting is in Ontario or remote", not bad_place, "; ".join(bad_place[:3]))
    check("filter", "every kept posting is internship, co-op or new grad", not bad_level, "; ".join(bad_level[:3]))
    code, sk = call("GET", "/api/filters/queue?view=skipped&limit=200")
    skipped = sk.get("postings", []) if code == 200 else []
    no_reason = [p for p in skipped if not (p.get("verdict_reasons") or p.get("reasons"))]
    check("filter", "every skipped posting says why", len(skipped) > 0 and not no_reason,
          f"{len(skipped)} skipped sampled, {len(no_reason)} without a reason")
    sample = skipped[0] if skipped else {}
    print(f"     example skip: {sample.get('company')} | {sample.get('title')} -> {sample.get('verdict_reasons') or sample.get('reasons')}")
    return kept


def _ts(p: dict) -> str:
    return p.get("posted_at") or p.get("first_seen_at") or ""


def step_order(kept: list[dict]) -> None:
    section("Order")
    stamps = [_ts(p) for p in kept]
    check("order", "newest first", stamps == sorted(stamps, reverse=True) or len(kept) < 2)
    fresh = [p for p in kept if p.get("posted_at")]
    if fresh:
        newest = max(fresh, key=_ts)
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(_ts(newest).replace("Z", "+00:00"))).total_seconds() / 3600
        check("order", "source posting dates recorded", True, f"{len(fresh)}/{len(kept)} have one; newest is {age_h:.0f} h old")
    else:
        check("order", "source posting dates recorded", False, "none of the kept postings carry a posted date")
    s = call("GET", "/api/settings")[1]["settings"]
    for order in ("deadline", "company"):
        s["queue"]["order_by"] = order
        call("PUT", "/api/settings", s)
        q = call("GET", "/api/filters/queue?view=kept&limit=500")[1].get("postings", [])
        if order == "company":
            names = [p["company"].lower() for p in q]
            check("order", "company A to Z", names == sorted(names))
        else:
            today = datetime.now(timezone.utc).date().isoformat()
            dl = [p.get("deadline") or "" for p in q]
            upcoming = [d for d in dl if d and d >= today]
            first = dl[:len(upcoming)]
            check("order", "soonest upcoming deadline first", first == sorted(upcoming),
                  f"{len(upcoming)} kept postings state an upcoming deadline")
    s["queue"]["order_by"] = "newest"
    call("PUT", "/api/settings", s)


def step_resume() -> None:
    section("Resume")
    code, pdf = call("GET", "/api/resume/preview?role_type=software", raw=True, timeout=300)
    is_pdf = code == 200 and isinstance(pdf, bytes) and pdf[:4] == b"%PDF"
    check("resume", "one-page PDF builds from the confirmed bank", is_pdf, f"{len(pdf) if is_pdf else code} bytes")
    code, files = call("GET", "/api/resume/files")
    check("resume", "resume files are listed", code == 200 and bool(files))


def step_apply(kept: list[dict]) -> dict | None:
    section("Apply (live, review mode, not submitted)")
    target = next((p for p in kept if p.get("source") in ("greenhouse", "lever", "ashby")), None)
    if not check("apply", "a simple-form posting is available", target is not None):
        return None
    print(f"     target: {target['company']} | {target['title']} | {target.get('url')}")
    pid = urllib.request.quote(target["id"], safe="")
    code, _ = call("POST", f"/api/filters/postings/{pid}/action", {"action": "approve"})
    check("apply", "approve from the queue", code == 200)
    code, r = call("POST", "/api/apply/run", {"limit": 1})
    if not check("apply", "apply run starts", code == 200 and "run_id" in r, str(r)[:120]):
        return None
    t = time.time()
    run = wait_run(r["run_id"], 1800)
    check("apply", "apply run finishes", run["status"] == "done", f"{time.time() - t:.0f} s: {run.get('summary', '')[:200]}")
    apps = call("GET", "/api/apply/applications")[1]
    app = next((a for a in apps if a.get("posting_id") == target["id"]), None)
    if not check("apply", "application row recorded", app is not None):
        return None
    check("apply", "review mode stopped before submitting", app["status"] in ("ready-to-submit", "needs-you"),
          f"status {app['status']}" + (f", needs you: {app.get('needs_you')}" if app.get("needs_you") else ""))
    check("apply", "a resume was attached", bool(app.get("resume_file")), Path(app.get("resume_file") or "").name)
    cost = call("GET", "/api/apply/cost")[1]
    check("apply", "cost per application measured", (cost.get("total_usd") or 0) > 0,
          f"${cost.get('total_usd')} for {cost.get('applications')} application(s)")
    return app


def step_answers() -> None:
    section("Answers")
    pend = call("GET", "/api/apply/answers?pending=1")[1]
    if pend:
        key = pend[0]["key"]
        code, saved = call("PUT", f"/api/apply/answers/{urllib.request.quote(key, safe='')}", {"answer": "Yes"})
        check("answers", "a pending question can be answered", code == 200 and saved.get("pending") == 0,
              f"{len(pend)} pending, answered: {pend[0]['question'][:60]}")
    else:
        code, saved = call("PUT", "/api/apply/answers/How%20did%20you%20hear%20about%20us", {"answer": "Job board"})
        check("answers", "an answer can be stored", code == 200 and saved.get("answer") == "Job board", "no pending questions")
    allq = call("GET", "/api/apply/answers")[1]
    check("answers", "answers are listed", len(allq) >= 1, f"{len(allq)} stored")


def step_replies(app: dict | None) -> None:
    section("Replies and insights")
    code, r = call("POST", "/api/tracker/sync", {})
    run = wait_run(r["run_id"], 120) if code == 200 and "run_id" in r else {"summary": str(r)}
    check("replies", "no inbox configured is reported plainly", "email" in (run.get("summary") or "").lower(),
          (run.get("summary") or "")[:120])
    if app is None:
        apps = call("GET", "/api/apply/applications")[1]
        app = apps[0] if apps else None
    if app is None:
        check("replies", "manual outcome", False, "no application to mark")
        return
    code, _ = call("POST", f"/api/tracker/applications/{app['id']}/outcome", {"outcome": "interview"})
    check("replies", "manual outcome saves", code == 200)
    stats = call("GET", "/api/tracker/stats")[1]
    tot = stats.get("totals", {})
    check("replies", "insights count the interview", tot.get("interviews") == 1 and tot.get("applications", 0) >= 1,
          f"{tot.get('interviews')} interview(s) from {tot.get('applications')} application(s)")
    check("replies", "small samples are labelled", "too few" in json.dumps(stats).lower())


def step_interface() -> None:
    section("Interface")
    chrome = find_chrome()
    if not check("interface", "a headless browser is available", chrome is not None):
        return
    for screen in ["", "jobs", "applications", "answers", "insights", "settings", "activity", "profile"]:
        url = f"{BASE}/#/{screen}"
        with tempfile.TemporaryDirectory() as prof:
            p = subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}",
                                "--virtual-time-budget=8000", "--dump-dom", url],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        dom = p.stdout
        body = dom.split("<body", 1)[-1]
        broken = any(s in body for s in ["Something went wrong", "Traceback", "Internal Server Error", "undefined undefined"])
        rendered = len(body) > 3000 and "<main" in body
        check("interface", f"screen '{screen or 'home'}' renders", rendered and not broken, f"{len(body)} chars")


def step_cli(env: dict) -> None:
    section("Command line")
    p = subprocess.run([PY, "-m", "applyfirst.cli", "--help"], capture_output=True, text=True, cwd=str(ROOT), env=env)
    check("cli", "help runs", p.returncode == 0 and "sweep" in p.stdout)
    p = subprocess.run([PY, "-m", "applyfirst.cli", "sync"], capture_output=True, text=True, cwd=str(ROOT), env=env)
    check("cli", "sync runs and reports", p.returncode == 0 and "sync:" in p.stdout, p.stdout.strip()[:120])


# --------------------------------------------------------------------------- main


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="fill one real form in review mode")
    ap.add_argument("--discover", action="store_true", help="run full board discovery on the first sweep")
    ap.add_argument("--keep", action="store_true", help="keep the temporary data home")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="applyfirst-e2e-"))
    home = work / "home"
    home.mkdir()
    env = {**os.environ, "APPLYFIRST_HOME": str(home), "APPLYFIRST_NO_SCHEDULER": "1"}
    port = free_port()
    BASE = f"http://127.0.0.1:{port}"
    print(f"data home: {home}\nserver: {BASE}", flush=True)

    pdf = make_resume_pdf(work)
    server = subprocess.Popen([PY, "-m", "applyfirst.cli", "serve", "--no-browser", "--port", str(port)],
                              cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/status", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("server did not start:", server.stderr.read().decode(errors="replace")[-2000:])
            return 2

        step_setup(pdf)
        step_find(home, args.discover)
        kept = step_filter()
        step_order(kept)
        step_resume()
        app = step_apply(kept) if args.apply and kept else None
        if not args.apply:
            print("\n== Apply skipped (run with --apply to fill one real form in review mode)")
        step_answers()
        step_replies(app)
        step_interface()
        step_cli(env)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    passed = sum(1 for r in results if r[2])
    failed = [r for r in results if not r[2]]
    print(f"\n== Result: {passed} passed, {len(failed)} failed")
    for area, name, _, detail in failed:
        print(f"  FAIL {area}: {name}  ({detail})")
    report = work / "e2e-report.json"
    report.write_text(json.dumps([dict(area=a, check=n, ok=o, detail=d) for a, n, o, d in results], indent=2), encoding="utf-8")
    print(f"report: {report}")
    if not args.keep and not failed:
        shutil.rmtree(home, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
