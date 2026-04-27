"""Command queue business logic."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException

import db


def take_next_pending(device_id: int) -> Optional[dict]:
    """Atomically pick oldest pending command for device and mark in_progress.

    Returns dict with command fields, or None if no pending.
    """
    with db.transaction("IMMEDIATE") as c:
        row = c.execute(
            "SELECT * FROM commands WHERE device_id = ? AND status = 'pending' "
            "ORDER BY id ASC LIMIT 1",
            (device_id,),
        ).fetchone()
        if row is None:
            return None
        c.execute(
            "UPDATE commands SET status = 'in_progress', taken_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'pending'",
            (row["id"],),
        )
        return dict(row)


def get_command(command_id: int) -> Optional[dict]:
    with db.get_conn() as c:
        r = c.execute("SELECT * FROM commands WHERE id = ?", (command_id,)).fetchone()
    return dict(r) if r else None


def list_commands(
    device_id: int,
    limit: int = 100,
    before_id: Optional[int] = None,
) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    with db.get_conn() as c:
        if before_id is not None:
            rows = c.execute(
                "SELECT * FROM commands WHERE device_id = ? AND id < ? "
                "ORDER BY id DESC LIMIT ?",
                (device_id, int(before_id), limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM commands WHERE device_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def create_command(
    device_id: int,
    name: str,
    payload: str,
    upload_id: Optional[int] = None,
) -> dict:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if len(name) > 64:
        raise HTTPException(status_code=400, detail="name too long (max 64)")

    from services.files import sanitize_command_name_for_dir
    if not sanitize_command_name_for_dir(name):
        raise HTTPException(status_code=400, detail="name has no allowed chars")

    payload = payload or ""

    input_file_path = None
    with db.get_conn() as c:
        if not c.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone():
            raise HTTPException(status_code=404, detail="device not found")

        if upload_id is not None:
            up = c.execute(
                "SELECT id, stored_path FROM uploads WHERE id = ?", (int(upload_id),)
            ).fetchone()
            if up is None:
                raise HTTPException(status_code=404, detail="upload not found")
            input_file_path = up["stored_path"]

        cur = c.execute(
            "INSERT INTO commands (device_id, name, payload, input_file_path) "
            "VALUES (?, ?, ?, ?)",
            (device_id, name, payload, input_file_path),
        )
        cmd_id = cur.lastrowid
        row = c.execute("SELECT * FROM commands WHERE id = ?", (cmd_id,)).fetchone()
    return dict(row)


def complete_command(
    command_id: int,
    device_id: int,
    new_status: str,
    output: str,
    output_file_rel: Optional[str],
) -> None:
    if new_status not in ("done", "error"):
        raise HTTPException(status_code=400, detail="status must be 'done' or 'error'")

    with db.transaction("IMMEDIATE") as c:
        row = c.execute(
            "SELECT id, device_id, status FROM commands WHERE id = ?", (command_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="command not found")
        if row["device_id"] != device_id:
            raise HTTPException(status_code=404, detail="command not found")
        if row["status"] != "in_progress":
            raise HTTPException(status_code=409, detail=f"command already {row['status']}")

        c.execute(
            "UPDATE commands SET status = ?, output = ?, output_file_path = COALESCE(?, output_file_path), "
            "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_status, output or "", output_file_rel, command_id),
        )


def commands_referencing_upload(stored_path: str) -> list[int]:
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id FROM commands WHERE input_file_path = ?", (stored_path,)
        ).fetchall()
    return [r["id"] for r in rows]
