"""Agent-facing endpoints (/api/agent/*)."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

import db
from auth import _client_ip, get_current_device
from config import Config
from services import commands as cmd_svc
from services import devices as dev_svc
from services.files import (
    sanitize_command_name_for_dir,
    sanitize_filename,
    stream_upload_to_file,
    timestamp_prefix,
)

log = logging.getLogger("agent")

router = APIRouter(prefix="/api/agent", tags=["agent"])

# populated at app build
_CFG: Config | None = None


def configure(cfg: Config) -> None:
    global _CFG
    _CFG = cfg


def _cfg() -> Config:
    if _CFG is None:
        raise RuntimeError("agent router not configured")
    return _CFG


class RegisterReq(BaseModel):
    mac: str = Field(...)
    hostname: str = Field(...)
    ip: str = Field(...)


@router.post("/register")
async def register(req: RegisterReq, request: Request):
    ip = req.ip or _client_ip(request)
    res = dev_svc.register_device(req.mac, req.hostname, ip)
    log.info("agent register: device_id=%s hostname=%s ip=%s", res["device_id"], req.hostname, ip)
    return res


@router.get("/command")
async def get_command(device: dict = Depends(get_current_device)):
    row = cmd_svc.take_next_pending(device["id"])
    if row is None:
        log.info("agent poll: device_id=%s no_command", device["id"])
        return Response(status_code=204)

    has_file = bool(row.get("input_file_path"))
    body = {
        "command_id": row["id"],
        "name": row["name"],
        "payload": row["payload"],
        "has_file": has_file,
        "file_url": f"/api/agent/command/{row['id']}/file" if has_file else None,
    }
    log.info("agent poll: device_id=%s gave command_id=%s", device["id"], row["id"])
    return body


@router.get("/command/{command_id}/file")
async def get_command_file(command_id: int, device: dict = Depends(get_current_device)):
    row = cmd_svc.get_command(command_id)
    if row is None or row["device_id"] != device["id"]:
        raise HTTPException(status_code=404, detail="command not found")
    rel = row.get("input_file_path")
    if not rel:
        raise HTTPException(status_code=404, detail="no input file")

    cfg = _cfg()
    target = (cfg.storage.uploads_dir / rel).resolve()
    try:
        target.relative_to(cfg.storage.uploads_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file missing")

    # original filename from uploads table
    with db.get_conn() as c:
        up = c.execute(
            "SELECT filename FROM uploads WHERE stored_path = ?", (rel,)
        ).fetchone()
    download_name = up["filename"] if up else target.name

    return FileResponse(
        path=str(target),
        filename=download_name,
        media_type="application/octet-stream",
    )


@router.post("/result")
async def post_result(
    request: Request,
    command_id: int = Form(...),
    status: str = Form(...),
    output: str = Form(""),
    file: UploadFile | None = File(None),
    device: dict = Depends(get_current_device),
):
    if status not in ("done", "error"):
        raise HTTPException(status_code=400, detail="status must be 'done' or 'error'")

    row = cmd_svc.get_command(command_id)
    if row is None or row["device_id"] != device["id"]:
        raise HTTPException(status_code=404, detail="command not found")
    if row["status"] != "in_progress":
        raise HTTPException(status_code=409, detail=f"command already {row['status']}")

    cfg = _cfg()
    output_file_rel: str | None = None

    if file is not None and file.filename:
        sanitized_cmd = sanitize_command_name_for_dir(row["name"]) or "_"
        sanitized_fn = sanitize_filename(file.filename)
        ts = timestamp_prefix()
        rel_path = f"{sanitized_cmd}/{ts}_{sanitized_fn}"
        target = cfg.storage.cmds_dir / rel_path

        # safety: target must stay under cmds_dir
        target_real = target.resolve()
        try:
            target_real.relative_to(cfg.storage.cmds_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid target path")

        await stream_upload_to_file(file, target_real, cfg.storage.max_upload_size_bytes)
        output_file_rel = rel_path

    cmd_svc.complete_command(
        command_id=command_id,
        device_id=device["id"],
        new_status=status,
        output=output,
        output_file_rel=output_file_rel,
    )
    log.info(
        "agent result: device_id=%s command_id=%s status=%s file=%s",
        device["id"], command_id, status, bool(output_file_rel),
    )
    return {"ok": True}
