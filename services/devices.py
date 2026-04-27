"""Device registration and listing."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Optional

import db

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def normalize_mac(mac: str) -> Optional[str]:
    if not mac or not _MAC_RE.match(mac):
        return None
    return mac.replace("-", ":").upper()


def register_device(mac_raw: str, hostname: str, ip: str) -> dict:
    mac = normalize_mac(mac_raw)
    if mac is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="invalid mac")
    hostname = (hostname or "").strip()
    if not hostname or len(hostname) > 255:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="invalid hostname")

    with db.get_conn() as c:
        row = c.execute(
            "SELECT * FROM devices WHERE mac = ? AND hostname = ?",
            (mac, hostname),
        ).fetchone()
        if row is not None:
            c.execute(
                "UPDATE devices SET last_ip = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
                (ip, row["id"]),
            )
            return {"device_id": row["id"], "token": row["token"]}

        token = secrets.token_urlsafe(32)
        cur = c.execute(
            "INSERT INTO devices (mac, hostname, last_ip, token) VALUES (?, ?, ?, ?)",
            (mac, hostname, ip, token),
        )
        return {"device_id": cur.lastrowid, "token": token}


def _parse_ts(ts: str) -> Optional[datetime]:
    """SQLite CURRENT_TIMESTAMP is UTC, format 'YYYY-MM-DD HH:MM:SS'."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None


def list_devices(online_threshold_sec: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, mac, hostname, last_ip, first_seen, last_seen FROM devices ORDER BY id"
        ).fetchall()

    out = []
    for r in rows:
        ls = _parse_ts(r["last_seen"]) if isinstance(r["last_seen"], str) else r["last_seen"]
        if isinstance(ls, datetime) and ls.tzinfo is None:
            ls = ls.replace(tzinfo=timezone.utc)
        online = False
        if ls is not None:
            online = (now - ls).total_seconds() < online_threshold_sec
        out.append({
            "id": r["id"],
            "mac": r["mac"],
            "hostname": r["hostname"],
            "last_ip": r["last_ip"],
            "last_seen": r["last_seen"] if isinstance(r["last_seen"], str) else (ls.isoformat() if ls else None),
            "online": online,
        })
    return out


def get_device(device_id: int) -> Optional[dict]:
    with db.get_conn() as c:
        r = c.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    return dict(r) if r else None
