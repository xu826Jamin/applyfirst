"""Other websites must not be able to drive the local app; Claude spend is capped."""
from fastapi.testclient import TestClient

from applyfirst import claude, config, store


def client():
    from applyfirst.server import app
    return TestClient(app)


def test_own_page_and_local_tools_are_allowed(tmp_home):
    c = client()
    assert c.get("/api/status").status_code == 200
    assert c.get("/api/status", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    assert c.put("/api/settings", json={}, headers={"Origin": "http://localhost:8765",
                                                    "Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_another_website_is_refused(tmp_home):
    c = client()
    evil = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    assert c.post("/api/apply/run", json={"limit": 5}, headers=evil).status_code == 403
    assert c.put("/api/secrets/imap_password", json={"value": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/profile", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_dns_rebinding_host_is_refused(tmp_home):
    c = client()
    assert c.get("/api/profile", headers={"Host": "attacker.example:8765"}).status_code == 403


def test_daily_cap_stops_claude_before_it_runs(tmp_home, monkeypatch):
    s = config.load_settings()
    s["claude"]["daily_budget_usd"] = 1
    config.save_settings(s)
    claude.record_spend(1.25, "earlier")
    called = []
    monkeypatch.setattr(claude.subprocess, "run", lambda *a, **k: called.append(1))
    r = claude.run("hello")
    assert not r.ok and "spending limit" in r.error
    assert called == []


def test_no_cap_when_zero(tmp_home):
    s = config.load_settings()
    s["claude"]["daily_budget_usd"] = 0
    config.save_settings(s)
    claude.record_spend(500, "x")
    assert claude.budget_left() is None


def test_background_claude_is_locked_down(tmp_home, monkeypatch):
    seen = {}

    class P:
        returncode, stdout, stderr = 0, '{"result": "ok", "total_cost_usd": 0}', ""

    def fake(cmd, **k):
        seen["cmd"] = cmd
        return P()

    monkeypatch.setattr(claude.subprocess, "run", fake)
    claude.run("x", browser="chrome-extension")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert cmd[cmd.index("--tools") + 1] == "ToolSearch"
    assert "bypassPermissions" not in cmd and "--dangerously-skip-permissions" not in cmd
    claude.run("x")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == ""


def test_read_rule_names_one_absolute_file():
    import os
    if os.name == "nt":
        assert claude.read_rule(r"C:\Users\a\.applyfirst\r\x.pdf") == "Read(//c/Users/a/.applyfirst/r/x.pdf)"
    else:
        assert claude.read_rule("/home/a/.applyfirst/r/x.pdf") == "Read(//home/a/.applyfirst/r/x.pdf)"


def test_upload_runs_read_only_their_files_from_an_empty_folder(tmp_home, monkeypatch):
    """Chrome's file_upload needs Read. Read must cover only the files to attach, and the run
    must not start in the applyfirst home, where Read would reach the profile and secrets."""
    import os
    seen = {}

    class P:
        returncode, stdout, stderr = 0, '{"result": "ok", "total_cost_usd": 0}', ""

    def fake(cmd, **k):
        seen["cmd"], seen["cwd"] = cmd, k.get("cwd")
        seen["cwd_files"] = os.listdir(k["cwd"]) if k.get("cwd") and os.path.isdir(k["cwd"]) else None
        return P()

    monkeypatch.setattr(claude.subprocess, "run", fake)
    resume = tmp_home / "resumes" / "Jo_Doe_Resume.pdf"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_bytes(b"%PDF-1.4")
    claude.run("apply", browser="chrome-extension", upload_files=[str(resume)])
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "ToolSearch,Read"
    reads = [a for a in cmd if a.startswith("Read(")]
    assert reads == [claude.read_rule(str(resume))]
    assert "*" not in reads[0]
    assert os.path.realpath(seen["cwd"]) != os.path.realpath(str(tmp_home))
    assert seen["cwd_files"] == []                       # an empty folder
    assert not os.path.exists(seen["cwd"])               # removed afterwards
    # without files to attach, no Read at all
    claude.run("apply", browser="chrome-extension")
    assert seen["cmd"][seen["cmd"].index("--tools") + 1] == "ToolSearch"
    assert not [a for a in seen["cmd"] if a.startswith("Read(")]


def test_chrome_runs_are_told_to_close_their_tabs(tmp_home, monkeypatch):
    seen = {}

    class P:
        returncode, stdout, stderr = 0, '{"result": "ok", "total_cost_usd": 0}', ""

    def fake(cmd, **k):
        seen["input"] = k.get("input")
        return P()

    monkeypatch.setattr(claude.subprocess, "run", fake)
    claude.run("find jobs", browser="chrome-extension")
    assert "tabs_close_mcp" in seen["input"] and seen["input"].startswith("find jobs")
    claude.run("find jobs", browser="playwright")
    assert "tabs_close_mcp" not in seen["input"]
    claude.run("find jobs")
    assert seen["input"] == "find jobs"
