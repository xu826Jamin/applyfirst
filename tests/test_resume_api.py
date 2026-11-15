"""resume: HTTP routes under /api/resume."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "resume"))
import bankdata  # noqa: E402
from minipdf import ALEX_RESUME, make_pdf  # noqa: E402

from applyfirst import claude  # noqa: E402
from applyfirst.resume import api, render  # noqa: E402


@pytest.fixture
def client(tmp_home, monkeypatch):
    monkeypatch.setattr(claude, "run", lambda *a, **k: claude.Result(False, error="no claude in tests"))
    app = FastAPI()
    app.include_router(api.router, prefix="/api/resume")
    return TestClient(app)


def test_import_edit_confirm_delete_flow(client, tmp_path):
    pdf = make_pdf(ALEX_RESUME, str(tmp_path / "alex.pdf"))
    with open(pdf, "rb") as f:
        r = client.post("/api/resume/import", files={"file": ("alex.pdf", f, "application/pdf")})
    assert r.status_code == 200
    rows = r.json()
    assert rows and all(x["confirmed"] == 0 for x in rows)
    assert len(client.get("/api/resume/experience").json()) == len(rows)

    bullet = next(x for x in rows if x["parent_id"] and "REST API" in x["text"])
    r = client.put(f"/api/resume/experience/{bullet['id']}", json={"text": "Built a REST API in Python",
                                                                 "tags": ["python"], "confirmed": True})
    assert r.status_code == 200 and r.json()["text"] == "Built a REST API in Python" and r.json()["confirmed"] == 1
    assert client.put("/api/resume/experience/E999", json={"text": "x"}).status_code == 404
    assert client.put(f"/api/resume/experience/{bullet['id']}", json={"section": "nope"}).status_code == 400

    r = client.post("/api/resume/experience", json={"section": "projects", "title": "Chess Bot"})
    assert r.status_code == 200 and r.json()["confirmed"] == 1 and r.json()["id"].startswith("E")
    new_id = r.json()["id"]
    r = client.post("/api/resume/experience", json={"parent_id": new_id, "text": "Wrote a move generator"})
    assert r.json()["id"] == f"{new_id}.b1"
    assert client.post("/api/resume/experience", json={"parent_id": "E404", "text": "x"}).status_code == 400

    r = client.post("/api/resume/experience/confirm-all")
    assert r.json()["confirmed"] > 5
    assert all(x["confirmed"] == 1 for x in client.get("/api/resume/experience").json())

    assert client.delete(f"/api/resume/experience/{new_id}").json() == {"deleted": new_id}
    assert client.delete(f"/api/resume/experience/{new_id}").status_code == 404
    assert not [x for x in client.get("/api/resume/experience").json() if x["parent_id"] == new_id]


def test_import_rejects_non_pdf_and_scans(client, tmp_path):
    r = client.post("/api/resume/import", files={"file": ("resume.docx", b"hello", "application/msword")})
    assert r.status_code == 400
    blank = make_pdf([""], str(tmp_path / "blank.pdf"))
    with open(blank, "rb") as f:
        r = client.post("/api/resume/import", files={"file": ("blank.pdf", f, "application/pdf")})
    assert r.status_code == 422 and "no readable text" in r.json()["detail"]
    with open(tmp_path / "bad.pdf", "wb") as f:
        f.write(b"not a pdf at all")
    with open(tmp_path / "bad.pdf", "rb") as f:
        assert client.post("/api/resume/import", files={"file": ("bad.pdf", f, "application/pdf")}).status_code == 422


def test_preview_and_files(client, alex, monkeypatch):
    assert client.get("/api/resume/preview").status_code == 409          # nothing confirmed yet
    bankdata.seed()
    r = client.get("/api/resume/preview", params={"role_type": "hardware"})
    assert r.status_code == 200
    if render.find_browser():
        assert r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    files = client.get("/api/resume/files").json()
    assert [f["name"] for f in files if "hardware" in f["name"]]
    name = files[0]["name"]
    assert client.get(f"/api/resume/files/{name}").status_code == 200
    assert client.get("/api/resume/files/../applyfirst.sqlite").status_code == 404
    assert client.get("/api/resume/files/nope.pdf").status_code == 404


def test_preview_without_a_browser_returns_html_and_says_why(client, alex, monkeypatch):
    monkeypatch.setattr(render, "find_browser", lambda: None)
    bankdata.seed()
    r = client.get("/api/resume/preview")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "No Chrome, Edge or Chromium" in r.headers["x-resume-note"]
    assert "Alex Rivera" in r.text


def test_files_never_list_the_imports_folder(client, tmp_path):
    pdf = make_pdf(ALEX_RESUME, str(tmp_path / "alex.pdf"))
    with open(pdf, "rb") as f:
        client.post("/api/resume/import", files={"file": ("alex.pdf", f, "application/pdf")})
    assert client.get("/api/resume/files").json() == []
