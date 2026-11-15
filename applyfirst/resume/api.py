"""Routes under /api/resume. See docs/CONTRACTS.md."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import bank, builder, parse

router = APIRouter()


def _row_out(r: dict) -> dict:
    return {k: r[k] for k in ("id", "parent_id", "section", "title", "org", "dates", "text", "tags",
                              "confirmed", "position")}


@router.post("/import")
def import_resume(file: UploadFile) -> list[dict]:
    name = (file.filename or "resume.pdf")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload your resume as a PDF.")
    d = builder.resumes_dir() / "imports"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^A-Za-z0-9._-]+', '_', name)[:80]}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        rows = parse.import_pdf(str(dest))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return [_row_out(r) for r in rows]


@router.get("/experience")
def list_experience() -> list[dict]:
    return [_row_out(r) for r in bank.all_rows()]


@router.post("/experience/confirm-all")
def confirm_all() -> dict:
    return {"confirmed": bank.confirm_all()}


@router.post("/experience")
def add_experience(body: dict) -> dict:
    body = dict(body)
    body.setdefault("confirmed", 1)          # a line the user types themselves is theirs
    try:
        return _row_out(bank.add(body))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/experience/{row_id}")
def update_experience(row_id: str, body: dict) -> dict:
    try:
        row = bank.update(row_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if row is None:
        raise HTTPException(404, "No such row.")
    return _row_out(row)


@router.delete("/experience/{row_id}")
def delete_experience(row_id: str) -> dict:
    if not bank.delete(row_id):
        raise HTTPException(404, "No such row.")
    return {"deleted": row_id}


@router.get("/preview")
def preview(role_type: str | None = None) -> FileResponse:
    try:
        res = builder.build_detailed(role_type or None, None, reuse=True)
    except ValueError as e:                  # BankEmpty is a ValueError
        raise HTTPException(409, str(e))
    media = "application/pdf" if res.kind == "pdf" else "text/html"
    headers = {"X-Resume-Note": res.note} if res.note else {}
    return FileResponse(res.path, media_type=media, headers=headers)


@router.get("/files")
def files() -> list[dict]:
    return builder.list_files()


@router.get("/files/{name:path}")
def get_file(name: str) -> FileResponse:
    root = builder.resumes_dir().resolve()
    p = (root / name).resolve()
    if root not in p.parents or not p.is_file() or p.suffix.lower() not in (".pdf", ".html"):
        raise HTTPException(404, "No such file.")
    return FileResponse(p, media_type="application/pdf" if p.suffix.lower() == ".pdf" else "text/html",
                        filename=p.name if p.suffix.lower() == ".pdf" else None)
