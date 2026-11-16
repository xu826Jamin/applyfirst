"""The status screen tells people when Chrome or Claude in Chrome is missing."""
from applyfirst import claude, config, server


def test_no_chrome_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(claude, "_chrome_exe_found", lambda: False)
    monkeypatch.setattr(claude, "_native_host_registered", lambda ud: False)
    info = claude.chrome_info(tmp_path / "missing")
    assert info == {"chrome": False, "extension": False, "connected": False}


def test_chrome_without_the_extension(tmp_path, monkeypatch):
    (tmp_path / "Default" / "Extensions" / "someotherextension").mkdir(parents=True)
    monkeypatch.setattr(claude, "_native_host_registered", lambda ud: False)
    info = claude.chrome_info(tmp_path)
    assert info["chrome"] is True and info["extension"] is False


def test_extension_in_a_second_profile_counts(tmp_path, monkeypatch):
    (tmp_path / "Default" / "Extensions").mkdir(parents=True)
    (tmp_path / "Profile 3" / "Extensions" / claude.EXTENSION_ID).mkdir(parents=True)
    monkeypatch.setattr(claude, "_native_host_registered", lambda ud: True)
    assert claude.chrome_info(tmp_path) == {"chrome": True, "extension": True, "connected": True}


def test_status_leaves_chrome_out_for_the_playwright_route(monkeypatch):
    monkeypatch.setattr(claude, "chrome_info", lambda: {"chrome": False, "extension": False, "connected": False})
    monkeypatch.setattr(config, "load_settings", lambda: {"apply": {"browser": "playwright"}})
    assert server._chrome_info() is None
    monkeypatch.setattr(config, "load_settings", lambda: {"apply": {"browser": "chrome-extension"}})
    assert server._chrome_info() == {"chrome": False, "extension": False, "connected": False}
