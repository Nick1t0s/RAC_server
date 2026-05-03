"""Jinja pages: /, /login, /logout."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import (
    _client_ip,
    _cfg as _auth_cfg,
    current_user,
    login_session,
    logout_session,
    verify_password,
)

log = logging.getLogger("pages")

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: Optional[str] = None):
    if current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    cfg = _auth_cfg()
    ip = _client_ip(request)
    ok = (username == cfg.auth.username) and verify_password(password, cfg.auth.password_hash)
    if not ok:
        log.warning("login failed: user=%s ip=%s", username, ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Неверный логин или пароль"},
            status_code=401,
        )
    login_session(request, username)
    log.info("login success: user=%s ip=%s", username, ip)
    return RedirectResponse(url="/", status_code=302)


@router.post("/logout")
async def logout(request: Request):
    logout_session(request)
    return RedirectResponse(url="/login", status_code=302)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"user": user},
    )


_HELP_DOCS = {
    "agent_md": Path("client/commands.md"),
    "windows_md": Path("client/windows_cmd.md"),
}


@router.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    ctx = {"user": user}
    for key, path in _HELP_DOCS.items():
        try:
            ctx[key] = path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("help: cannot read %s: %s", path, e)
            ctx[key] = f"# Файл недоступен\n\n`{path}`: {e}"
    return templates.TemplateResponse(request, "help.html", ctx)
