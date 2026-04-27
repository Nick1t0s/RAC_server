"""Auth helpers: bcrypt password verify, web session dep, agent bearer dep."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from passlib.hash import bcrypt

import db
from config import Config

log = logging.getLogger("auth")

# populated at app build time
_CONFIG: Optional[Config] = None


def configure(cfg: Config) -> None:
    global _CONFIG
    _CONFIG = cfg


def _cfg() -> Config:
    if _CONFIG is None:
        raise RuntimeError("auth.configure() must be called first")
    return _CONFIG


# ---------- web session ----------

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.verify(plain, hashed)
    except Exception:
        return False


def login_session(request: Request, username: str) -> None:
    request.session["user"] = username
    request.session["login_at"] = datetime.utcnow().isoformat()


def logout_session(request: Request) -> None:
    request.session.clear()


def current_user(request: Request) -> Optional[str]:
    return request.session.get("user")


def require_user_api(request: Request) -> str:
    """Dep for /api/web/* — raises 401 JSON if no session."""
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


# ---------- agent bearer token ----------

def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # leftmost = original client
        first = fwd.split(",")[0].strip()
        if first:
            return first
    if request.client:
        return request.client.host
    return ""


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, value = parts
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None


def get_current_device(request: Request) -> dict:
    """Look up device by Authorization: Bearer token; update last_seen/last_ip.

    Raises 401 if missing/invalid token.
    Returns dict-like row of the device.
    """
    token = _extract_bearer(request.headers.get("authorization"))
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")

    ip = _client_ip(request)

    with db.get_conn() as c:
        row = c.execute(
            "SELECT * FROM devices WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="invalid token")

        # constant-time check just in case (token stored equals provided)
        if not secrets.compare_digest(row["token"], token):
            raise HTTPException(status_code=401, detail="invalid token")

        c.execute(
            "UPDATE devices SET last_seen = CURRENT_TIMESTAMP, last_ip = ? WHERE id = ?",
            (ip, row["id"]),
        )
        return dict(row)
