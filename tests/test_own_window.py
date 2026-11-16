"""The applyfirst Chrome window: which route a run takes, how the window starts, and how Claude
is attached to it. Nothing here starts a real browser or the real Claude Code."""
import json
import os

import pytest

from applyfirst import claude, config, own_window, server
from applyfirst.apply import brief as brief_mod

READY = {"chrome": True, "extension": True, "connected": True}
NO_EXT = {"chrome": True, "extension": False, "connected": False}
NOT_LINKED = {"chrome": True, "extension": True, "connected": False}


# --------------------------------------------------------------------------- route choice


def test_auto_uses_your_own_chrome_only_when_fully_set_up():
    assert claude.resolve_browser("auto", READY) == "chrome-extension"
    assert claude.resolve_browser("auto", NO_EXT) == "own-window"
    assert claude.resolve_browser("auto", NOT_LINKED) == "own-window"
    assert claude.resolve_browser("auto", {"chrome": False, "extension": False, "connected": False}) == "own-window"


def test_explicit_choices_are_honored_even_when_chrome_is_ready_or_not():
    assert claude.resolve_browser("chrome-extension", NO_EXT) == "chrome-extension"
    assert claude.resolve_browser("own-window", READY) == "own-window"


def test_the_old_playwright_value_is_the_own_window():
    assert claude.resolve_browser("playwright", READY) == "own-window"


def test_default_setting_is_auto(tmp_home):
    assert config.load_settings()["apply"]["browser"] == "auto"


def test_an_older_settings_file_with_the_old_default_becomes_auto(tmp_home):
    (tmp_home / "settings.json").write_text(json.dumps({"apply": {"browser": "chrome-extension"}}), encoding="utf-8")
    assert config.load_settings()["apply"]["browser"] == "auto"
    # saved by this version, the same value is a choice and is kept
    s = config.load_settings()
    s["apply"]["browser"] = "chrome-extension"
    config.save_settings(s)
    assert config.load_settings()["apply"]["browser"] == "chrome-extension"


def test_a_saved_playwright_setting_reads_as_own_window(tmp_home):
    (tmp_home / "settings.json").write_text(json.dumps({"apply": {"browser": "playwright"}}), encoding="utf-8")
    assert config.load_settings()["apply"]["browser"] == "own-window"


def test_status_reports_the_route_in_use(tmp_home, monkeypatch):
    monkeypatch.setattr(claude, "chrome_info", lambda: NO_EXT)
    monkeypatch.setattr(own_window, "node_ok", lambda: False)
    from applyfirst.resume import render
    monkeypatch.setattr(render, "find_browser", lambda: "/x/chrome")
    assert server._chrome_info() is None
    assert server._own_window_info() == {"node": False, "browser": True}
    monkeypatch.setattr(claude, "chrome_info", lambda: READY)
    assert server._chrome_info() == READY
    assert server._own_window_info() is None


# --------------------------------------------------------------------------- the launcher


def test_launch_command_binds_to_this_computer_and_uses_its_own_profile():
    cmd = own_window.launch_command("/x/chrome", 9444, "/home/a/.applyfirst/browser-window")
    assert cmd[0] == "/x/chrome"
    assert "--remote-debugging-port=9444" in cmd
    assert "--remote-debugging-address=127.0.0.1" in cmd
    assert "--user-data-dir=/home/a/.applyfirst/browser-window" in cmd
    assert "--no-first-run" in cmd and "--no-default-browser-check" in cmd
    assert not any("--headless" in a for a in cmd)


def test_an_open_window_is_reused_not_started_again(tmp_home, monkeypatch):
    config.path(own_window.STATE_FILE).write_text(json.dumps({"port": 9555}), encoding="utf-8")
    monkeypatch.setattr(own_window, "alive", lambda port, timeout=1.5: port == 9555)
    monkeypatch.setattr(own_window, "_start", lambda cmd: pytest.fail("started a second window"))
    assert own_window._ensure() == (9555, "")


def test_a_closed_window_is_started_on_its_own_profile_and_remembered(tmp_home, monkeypatch):
    started = []
    answering = {"on": False}
    monkeypatch.setattr(own_window.render, "find_browser", lambda: "/x/chrome")
    monkeypatch.setattr(own_window, "_free_port", lambda: 9666)

    def start(cmd):
        started.append(cmd)
        answering["on"] = True

    monkeypatch.setattr(own_window, "_start", start)
    monkeypatch.setattr(own_window, "alive", lambda port, timeout=1.5: answering["on"] and port == 9666)
    assert own_window._ensure(timeout=2) == (9666, "")
    assert len(started) == 1
    assert f"--user-data-dir={own_window.profile_dir()}" in started[0]
    assert own_window.profile_dir().parent == tmp_home            # inside the applyfirst home, never the user's Chrome
    assert json.loads(config.path(own_window.STATE_FILE).read_text())["port"] == 9666
    # the next call finds it listening and starts nothing
    monkeypatch.setattr(own_window, "_start", lambda cmd: pytest.fail("started a second window"))
    assert own_window._ensure() == (9666, "")


def test_a_stale_saved_port_does_not_stop_a_fresh_start(tmp_home, monkeypatch):
    config.path(own_window.STATE_FILE).write_text(json.dumps({"port": 9111}), encoding="utf-8")
    started = []
    monkeypatch.setattr(own_window.render, "find_browser", lambda: "/x/chrome")
    monkeypatch.setattr(own_window, "_free_port", lambda: 9222)
    monkeypatch.setattr(own_window, "_start", lambda cmd: started.append(cmd))
    monkeypatch.setattr(own_window, "alive", lambda port, timeout=1.5: bool(started) and port == 9222)
    assert own_window._ensure(timeout=2)[0] == 9222


def test_no_browser_on_the_computer_says_so_plainly(tmp_home, monkeypatch):
    monkeypatch.setattr(own_window.render, "find_browser", lambda: None)
    port, why = own_window._ensure()
    assert port is None and "Chrome" in why


def test_a_window_that_never_answers_is_a_clear_failure(tmp_home, monkeypatch):
    monkeypatch.setattr(own_window.render, "find_browser", lambda: "/x/chrome")
    monkeypatch.setattr(own_window, "_free_port", lambda: 9777)
    monkeypatch.setattr(own_window, "_start", lambda cmd: None)
    monkeypatch.setattr(own_window, "alive", lambda port, timeout=1.5: False)
    port, why = own_window._ensure(timeout=0.5)
    assert port is None and "did not start" in why
    assert not config.path(own_window.STATE_FILE).exists()


def test_mcp_config_attaches_over_the_local_debugging_port():
    cfg = own_window.mcp_config(9333)
    assert "--cdp-endpoint" in cfg["args"]
    assert cfg["args"][cfg["args"].index("--cdp-endpoint") + 1] == "http://127.0.0.1:9333"
    assert "--user-data-dir" not in cfg["args"]            # it never opens a browser of its own


# --------------------------------------------------------------------------- the Claude run


class _P:
    returncode, stdout, stderr = 0, '{"result": "ok", "total_cost_usd": 0}', ""


def _capture(monkeypatch):
    seen = {}

    def fake(cmd, **k):
        seen["cmd"], seen["input"], seen["cwd"] = cmd, k.get("input"), k.get("cwd")
        cfg = cmd[cmd.index("--mcp-config") + 1] if "--mcp-config" in cmd else None
        seen["mcp"] = json.load(open(cfg, encoding="utf-8")) if cfg else None
        seen["files"] = ([os.path.relpath(os.path.join(d, f), k["cwd"]) for d, _, fs in os.walk(k["cwd"]) for f in fs]
                         if k.get("cwd") and os.path.isdir(k["cwd"]) else None)
        return _P()

    monkeypatch.setattr(claude.subprocess, "run", fake)
    return seen


def test_own_window_run_connects_to_the_window_and_may_use_only_its_tools(tmp_home, monkeypatch):
    seen = _capture(monkeypatch)
    claude.run("fill", browser="own-window")
    cmd = seen["cmd"]
    assert "--chrome" not in cmd
    assert "mcp__playwright__*" in cmd
    assert cmd[cmd.index("--tools") + 1] == "ToolSearch"
    args = seen["mcp"]["mcpServers"]["playwright"]["args"]
    assert args[args.index("--cdp-endpoint") + 1] == "http://127.0.0.1:9333"


def test_playwright_and_auto_settings_take_the_same_route(tmp_home, monkeypatch):
    monkeypatch.setattr(claude, "chrome_info", lambda: NO_EXT)
    seen = _capture(monkeypatch)
    for value in ("playwright", "auto"):
        seen.clear()
        claude.run("fill", browser=value)
        assert "mcp__playwright__*" in seen["cmd"]


def test_auto_run_uses_your_own_chrome_when_it_is_ready(tmp_home, monkeypatch):
    monkeypatch.setattr(claude, "chrome_info", lambda: READY)
    seen = _capture(monkeypatch)
    claude.run("fill", browser="auto")
    assert "--chrome" in seen["cmd"] and "mcp__claude-in-chrome__*" in seen["cmd"]


def test_the_window_profile_cannot_be_read_by_a_run(tmp_home, monkeypatch):
    seen = _capture(monkeypatch)
    claude.run("fill", browser="own-window")
    cmd = seen["cmd"]
    deny = cmd[cmd.index("--disallowedTools") + 1]
    assert deny.startswith("Read(") and deny.endswith("/**)")
    assert claude.read_rule(str(own_window.profile_dir())).rstrip(")") in deny
    # and the run starts in an empty folder, not in the applyfirst home that holds the profile
    assert os.path.realpath(seen["cwd"]) != os.path.realpath(str(tmp_home))
    assert seen["files"] == []
    assert not os.path.exists(seen["cwd"])


def test_files_to_attach_are_copied_into_the_run_folder_and_the_prompt_points_there(tmp_home, monkeypatch):
    seen = _capture(monkeypatch)
    resume = tmp_home / "resumes" / "Jo_Doe_Resume.pdf"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_bytes(b"%PDF-1.4")
    claude.run(f"upload {resume} please", browser="own-window", upload_files=[str(resume)])
    assert [os.path.basename(f) for f in seen["files"]] == ["Jo_Doe_Resume.pdf"]
    assert str(resume) not in seen["input"] and "Jo_Doe_Resume.pdf" in seen["input"]
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "ToolSearch"          # no Read: the browser attaches the file


def test_own_window_run_leaves_the_window_open_and_the_review_tab_alone(tmp_home, monkeypatch):
    seen = _capture(monkeypatch)
    claude.run("find jobs", browser="own-window")
    assert "Never call browser_close" in seen["input"]
    assert "never close the last tab" in " ".join(seen["input"].lower().split())
    assert "tabs_close_mcp" not in seen["input"]
    assert "leave that one" in seen["input"]


def test_no_node_is_a_plain_failure_not_a_hang(tmp_home, monkeypatch):
    monkeypatch.setattr(own_window, "node_ok", lambda: False)
    monkeypatch.setattr(claude.subprocess, "run", lambda *a, **k: pytest.fail("ran Claude without Node"))
    res = claude.run("fill", browser="own-window")
    assert not res.ok and "Node.js" in res.error


def test_a_window_that_will_not_open_is_a_plain_failure(tmp_home, monkeypatch):
    monkeypatch.setattr(own_window, "ensure_window", lambda: (None, "applyfirst's Chrome window did not start."))
    monkeypatch.setattr(claude.subprocess, "run", lambda *a, **k: pytest.fail("ran Claude without a window"))
    res = claude.run("fill", browser="own-window")
    assert not res.ok and "did not start" in res.error


# --------------------------------------------------------------------------- the brief


def test_the_brief_names_the_playwright_script_tool_on_this_route():
    assert brief_mod._js_tool("own-window") == "browser_evaluate"
    assert brief_mod._js_tool("playwright") == "browser_evaluate"
    assert brief_mod._js_tool("chrome-extension") == "javascript_tool"
    assert "async () =>" in brief_mod._workday_section({"firstName": "A"}, "own-window")
    assert "async () =>" not in brief_mod._workday_section({"firstName": "A"}, "chrome-extension")


def test_a_workday_run_may_read_the_filler_on_both_routes(tmp_home, monkeypatch):
    from applyfirst.apply.brief import WORKDAY_JS
    for route in ("own-window", "chrome-extension"):
        seen = _capture(monkeypatch)
        claude.run("fill", browser=route, read_files=[str(WORKDAY_JS)])
        cmd = seen["cmd"]
        assert "Read" in cmd[cmd.index("--tools") + 1].split(",")
        assert claude.read_rule(str(WORKDAY_JS)) in cmd


def test_a_plain_own_window_run_gets_no_read_tool(tmp_home, monkeypatch):
    seen = _capture(monkeypatch)
    claude.run("fill", browser="own-window")
    cmd = seen["cmd"]
    assert "Read" not in cmd[cmd.index("--tools") + 1].split(",")
