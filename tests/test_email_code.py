"""Emailed application codes: found in the inbox, sign-in codes refused, served to the filling session."""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from applyfirst import claude, store
from applyfirst.apply import _finish, email_code
from applyfirst.apply.brief import build_brief

NOW = datetime(2026, 11, 16, 4, 20, tzinfo=timezone.utc)
SINCE = NOW - timedelta(minutes=3)


def msg(subject, body, minutes_ago=0, frm="no-reply@us.greenhouse-mail.io"):
    return {"from": frm, "subject": subject, "body": body,
            "date": (NOW - timedelta(minutes=minutes_ago)).isoformat()}


GH = msg("Security code for your application to Acme",
         "Copy and paste this code into the security code field on your application: 59215524 "
         "After you enter the code, resubmit your application. (c) 2026 Greenhouse 18 West 18th Street")
LOGIN = msg("Here's your MyGreenhouse security code",
            "Hi, Your security code is: 10524169 Enter this code on the MyGreenhouse sign-in page to continue.")


def test_application_code_is_found():
    assert email_code.extract_code(GH) == "59215524"
    other = msg("Verify your application", "Your verification code is A7K2Q9. Enter it to finish applying.")
    assert email_code.extract_code(other) == "A7K2Q9"


def test_sign_in_and_unrelated_codes_are_refused():
    assert email_code.extract_code(LOGIN) is None
    portal = msg("Your sign-in code", "Sign in to check on your application. Your security code is 10524169.")
    assert email_code.extract_code(portal) is None
    assert email_code.extract_code(msg("Reset your password", "Your application portal code is 123456")) is None
    assert email_code.extract_code(msg("Your order", "Use discount code SAVE2026 at checkout")) is None


def test_only_mail_after_the_application_started_counts():
    old = msg(GH["subject"], GH["body"].replace("59215524", "11112222"), minutes_ago=30)
    assert email_code.pick([old], SINCE) is None
    assert email_code.pick([old, GH], SINCE) == "59215524"


def test_the_code_naming_the_company_wins():
    a = msg("Security code for your application to Other Co", "this code into the security code field on your application: 33334444", minutes_ago=0)
    b = msg("Security code for your application to Acme", "this code into the security code field on your application: 55556666", minutes_ago=1)
    assert email_code.pick([a, b], SINCE, "Acme") == "55556666"


def test_wait_polls_until_the_code_arrives_and_gives_up_loudly():
    calls = []

    def fetch(since):
        calls.append(1)
        return [GH] if len(calls) >= 3 else []

    assert email_code.wait_for_code(SINCE, "Acme", 300, fetch=fetch, sleep=lambda s: None) == "CODE: 59215524"
    assert len(calls) == 3
    out = email_code.wait_for_code(SINCE, "Acme", 0, fetch=lambda s: [], sleep=lambda s: None)
    assert out.startswith("No code email arrived")

    def broken(since):
        raise RuntimeError("Email is not connected in Settings.")
    assert email_code.wait_for_code(SINCE, "", 0, fetch=broken).startswith("Could not read the inbox")


def test_the_server_speaks_mcp(tmp_home):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "wait_for_email_code", "arguments": {"max_wait_seconds": 0}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_inbox"}},
    ]
    p = subprocess.run([sys.executable, "-m", "applyfirst.apply.email_code"],
                       input="\n".join(json.dumps(x) for x in lines) + "\n",
                       capture_output=True, text=True, timeout=60,
                       env={**__import__("os").environ, "APPLYFIRST_HOME": str(tmp_home)})
    out = {r["id"]: r for r in map(json.loads, p.stdout.splitlines())}
    assert out[1]["result"]["protocolVersion"] == "2025-06-18"
    assert [t["name"] for t in out[2]["result"]["tools"]] == ["wait_for_email_code"]
    text = out[3]["result"]["content"][0]["text"]
    assert text.startswith("Could not read the inbox") and out[3]["result"]["isError"]
    assert "error" in out[4]


def _brief(mode, tool):
    return build_brief({"company": "Acme", "title": "Intern"}, mode=mode, resume_path="r.pdf",
                       cover_letter_path=None, cover_letters_setting="when-required",
                       standard={"commitments": {"policy": "yes"}}, learned=[], experience=[],
                       settings_apply={}, browser="chrome-extension", email_code_tool=tool)


def test_brief_tells_auto_mode_what_to_do_with_a_code():
    assert "Call wait_for_email_code" in _brief("auto", True)
    manual = _brief("auto", False)
    assert "wait_for_email_code" not in manual and "Connect your email" in manual
    assert "EMAILED" not in _brief("review", True)


def test_run_registers_the_server_and_allows_only_its_tools(tmp_home, monkeypatch):
    seen = {}

    class P:
        returncode, stdout, stderr = 0, '{"result": "ok", "total_cost_usd": 0}', ""

    def fake(cmd, **k):
        seen["cmd"] = cmd
        i = cmd.index("--mcp-config")
        with open(cmd[i + 1], encoding="utf-8") as f:
            seen["mcp"] = json.load(f)
        return P()

    monkeypatch.setattr(claude.subprocess, "run", fake)
    cfg = email_code.server_config("Acme")
    claude.run("x", browser="chrome-extension", mcp_servers={"applyfirst": cfg})
    assert seen["mcp"]["mcpServers"]["applyfirst"]["args"] == ["-m", "applyfirst.apply.email_code"]
    assert "mcp__applyfirst__*" in seen["cmd"]
    assert seen["mcp"]["mcpServers"]["applyfirst"]["env"]["APPLYFIRST_CODE_COMPANY"] == "Acme"


def test_file_fields_never_become_questions(tmp_home):
    store.execute("INSERT INTO applications (posting_id, company, title, status, created_at, updated_at) "
                  "VALUES ('p','Acme','Intern','filling',?,?)", (store.now(), store.now()))
    app_id = store.one("SELECT id FROM applications")["id"]
    res = claude.Result(True, structured={"status": "needs-you", "needs_you_reason": "Upload refused.",
                                          "pending_questions": [{"question": "Resume", "type": "file"}]})
    status, reason = _finish(app_id, res, "auto", {})
    assert status == "needs-you" and reason == "Upload refused."
    assert store.rows("SELECT * FROM answers") == []
