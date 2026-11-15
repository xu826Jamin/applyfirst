"""The web interface is served as plain static files: no build step, no CDN."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from applyfirst.server import WEB, app

MODULES = ["app.js", "lib.js", "setup.js", "settings.js"]


@pytest.fixture
def client(tmp_home):
    return TestClient(app)


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "/static/app.js" in r.text and "/static/styles.css" in r.text
    assert 'id="content"' in r.text and 'lang="en"' in r.text


def test_assets_served(client):
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    css = client.get("/static/styles.css")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert "prefers-color-scheme: dark" in css.text


def test_modules_served(client):
    for name in MODULES:
        assert client.get(f"/static/{name}").status_code == 200, name


def test_no_cdn_and_no_em_dashes():
    for p in [WEB / "index.html", WEB / "styles.css", *(WEB / m for m in MODULES)]:
        text = p.read_text(encoding="utf-8")
        assert "—" not in text, f"em dash in {p.name}"
        assert not re.search(r"https?://(cdn|unpkg|fonts)\.", text), f"external asset in {p.name}"


def test_relative_imports_exist():
    for m in MODULES:
        for target in re.findall(r'from "\./([\w.-]+)"', (WEB / m).read_text(encoding="utf-8")):
            assert (WEB / target).exists(), f"{m} imports missing {target}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_parses(tmp_path):
    for m in MODULES:
        copy = tmp_path / (Path(m).stem + ".mjs")
        copy.write_text((WEB / m).read_text(encoding="utf-8"), encoding="utf-8")
        r = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True)
        assert r.returncode == 0, f"{m}: {r.stderr}"


def test_screens_survive_missing_routes(client):
    # Every call the interface makes may 404 while a package is not installed; the shared
    # routes must always answer so the shell can render.
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/runs").status_code == 200
