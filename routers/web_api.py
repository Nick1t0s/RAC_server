"""Web admin JSON API (/api/web/*). Session cookie required."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from urllib.parse import quote

import db
from auth import require_user_api
from config import Config
from services import commands as cmd_svc
from services import devices as dev_svc
from services.files import (
    safe_path,
    sanitize_filename,
    stream_upload_to_file,
    timestamp_prefix,
)

log = logging.getLogger("web_api")

router = APIRouter(prefix="/api/web", tags=["web"], dependencies=[Depends(require_user_api)])

_CFG: Config | None = None


def configure(cfg: Config) -> None:
    global _CFG
    _CFG = cfg


def _cfg() -> Config:
    if _CFG is None:
        raise RuntimeError("web_api not configured")
    return _CFG


# ---------- devices ----------

@router.get("/devices")
async def list_devices():
    cfg = _cfg()
    return dev_svc.list_devices(cfg.polling.online_threshold_sec)


# ---------- commands ----------

def _file_url_for_output(rel: str) -> str:
    return f"/api/web/files/download?path={quote(rel, safe='/')}"


def _row_to_command_dto(row: dict) -> dict:
    input_file = None
    if row.get("input_file_path"):
        with db.get_conn() as c:
            up = c.execute(
                "SELECT id, filename FROM uploads WHERE stored_path = ?",
                (row["input_file_path"],),
            ).fetchone()
        if up:
            input_file = {
                "filename": up["filename"],
                "url": f"/api/web/uploads/{up['id']}/download",
            }
        else:
            input_file = {
                "filename": Path(row["input_file_path"]).name,
                "url": None,
            }

    output_file = None
    if row.get("output_file_path"):
        rel = row["output_file_path"]
        output_file = {
            "filename": Path(rel).name,
            "url": _file_url_for_output(rel),
        }

    return {
        "id": row["id"],
        "name": row["name"],
        "payload": row["payload"],
        "status": row["status"],
        "output": row["output"],
        "created_at": row["created_at"],
        "taken_at": row.get("taken_at"),
        "completed_at": row.get("completed_at"),
        "input_file": input_file,
        "output_file": output_file,
    }


@router.get("/commands")
async def list_commands(
    device_id: int = Query(..., ge=1),
    limit: int = Query(100, ge=1, le=500),
    before_id: Optional[int] = Query(None, ge=1),
):
    rows = cmd_svc.list_commands(device_id=device_id, limit=limit, before_id=before_id)
    return [_row_to_command_dto(r) for r in rows]


class CreateCommandReq(BaseModel):
    device_id: int = Field(..., ge=1)
    name: str = Field(...)
    payload: str = Field("")
    upload_id: Optional[int] = Field(None)


@router.delete("/commands")
async def clear_commands(device_id: int = Query(..., ge=1)):
    cfg = _cfg()
    res = cmd_svc.clear_device_commands(device_id)
    base = cfg.storage.cmds_dir.resolve()
    removed_files = 0
    for rel in res["output_files"]:
        try:
            target = (cfg.storage.cmds_dir / rel).resolve()
            target.relative_to(base)
        except ValueError:
            continue
        try:
            if target.exists() and target.is_file():
                target.unlink()
                removed_files += 1
        except OSError as e:
            log.warning("failed to remove output file %s: %s", target, e)
    return {"ok": True, "deleted": res["deleted"], "removed_files": removed_files}


@router.post("/commands")
async def create_command(req: CreateCommandReq):
    row = cmd_svc.create_command(
        device_id=req.device_id,
        name=req.name,
        payload=req.payload,
        upload_id=req.upload_id,
    )
    return _row_to_command_dto(row)


# ---------- uploads ----------

@router.get("/uploads")
async def list_uploads():
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, filename, stored_path, size_bytes, uploaded_at "
            "FROM uploads ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/uploads")
async def create_upload(file: UploadFile = File(...)):
    cfg = _cfg()
    original = file.filename or "file"
    sanitized = sanitize_filename(original)
    ts = timestamp_prefix()
    stored_rel = f"{ts}_{sanitized}"
    target = cfg.storage.uploads_dir / stored_rel

    # safety
    target_real = target.resolve()
    try:
        target_real.relative_to(cfg.storage.uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")

    size = await stream_upload_to_file(file, target_real, cfg.storage.max_upload_size_bytes)

    with db.get_conn() as c:
        cur = c.execute(
            "INSERT INTO uploads (filename, stored_path, size_bytes) VALUES (?, ?, ?)",
            (original, stored_rel, size),
        )
        up_id = cur.lastrowid
        row = c.execute("SELECT * FROM uploads WHERE id = ?", (up_id,)).fetchone()
    return dict(row)


@router.get("/uploads/{upload_id}/download")
async def download_upload(upload_id: int):
    cfg = _cfg()
    with db.get_conn() as c:
        r = c.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail="upload not found")

    target = (cfg.storage.uploads_dir / r["stored_path"]).resolve()
    try:
        target.relative_to(cfg.storage.uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="file missing")
    return FileResponse(
        path=str(target),
        filename=r["filename"],
        media_type="application/octet-stream",
    )


@router.delete("/uploads/{upload_id}")
async def delete_upload(upload_id: int):
    cfg = _cfg()
    with db.get_conn() as c:
        r = c.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail="upload not found")

    refs = cmd_svc.commands_referencing_upload(r["stored_path"])
    if refs:
        return JSONResponse(
            status_code=409,
            content={"detail": "upload is referenced by commands", "command_ids": refs},
        )

    target = (cfg.storage.uploads_dir / r["stored_path"]).resolve()
    try:
        target.relative_to(cfg.storage.uploads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    try:
        if target.exists():
            target.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"unlink failed: {e}")

    with db.get_conn() as c:
        c.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
    return {"ok": True}


# ---------- cmds/ explorer ----------

@router.get("/files")
async def list_files(path: str = Query("")):
    cfg = _cfg()
    base = cfg.storage.cmds_dir
    target = safe_path(base, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")

    rel = "" if target == base.resolve() else str(target.relative_to(base.resolve())).replace(os.sep, "/")
    parent = ""
    if rel:
        parent_path = str(Path(rel).parent).replace(os.sep, "/")
        parent = "" if parent_path in (".", "") else parent_path

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.is_dir():
                items.append({"name": entry.name, "type": "dir"})
            else:
                try:
                    st = entry.stat()
                    items.append({
                        "name": entry.name,
                        "type": "file",
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    })
                except OSError:
                    continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="permission denied")

    return {"path": rel, "parent": parent, "items": items}


@router.get("/files/download")
async def download_file(path: str = Query(...)):
    cfg = _cfg()
    target = safe_path(cfg.storage.cmds_dir, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="application/octet-stream",
    )


@router.delete("/files")
async def delete_file(path: str = Query(...)):
    cfg = _cfg()
    target = safe_path(cfg.storage.cmds_dir, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="cannot delete directory")
    try:
        target.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"unlink failed: {e}")
    return {"ok": True}
