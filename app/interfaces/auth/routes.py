"""Owner gate login / logout / refresh (JWT cookies)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER

from app.infrastructure.gate_auth import (
    ADMIN_SESSION_KEY,
    clear_auth_cookies,
    const_eq,
    set_auth_cookies,
    try_refresh_username,
    username_from_request,
)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def create_auth_router() -> APIRouter:
    router = APIRouter(tags=["auth"])

    def _settings(request: Request):
        return request.app.state.settings

    @router.get("/login", response_class=HTMLResponse)
    def login_get(request: Request) -> Response:
        settings = _settings(request)
        if not settings.gate_enabled():
            return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)
        if username_from_request(request, settings):
            return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {
                "app_name": settings.app_name,
                "error": None,
            },
        )

    @router.post("/login", response_class=HTMLResponse)
    def login_post(
        request: Request,
        name: str = Form(...),
        password: str = Form(...),
    ) -> Response:
        settings = _settings(request)
        if not settings.gate_enabled():
            return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)
        creds = settings.gate_credentials()
        assert creds is not None
        expect_user, expect_pass = creds
        user_ok = const_eq(name.strip(), expect_user)
        pass_ok = const_eq(password, expect_pass)
        if not (user_ok and pass_ok):
            return TEMPLATES.TemplateResponse(
                request,
                "login.html",
                {
                    "app_name": settings.app_name,
                    "error": "invalid",
                },
                status_code=401,
            )
        request.session[ADMIN_SESSION_KEY] = True
        response = RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)
        set_auth_cookies(response, settings, expect_user)
        return response

    @router.post("/logout")
    @router.get("/logout")
    def logout(request: Request) -> Response:
        settings = _settings(request)
        request.session.clear()
        response = RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
        response.headers["Cache-Control"] = "no-store"
        clear_auth_cookies(response, settings)
        return response

    @router.post("/api/auth/refresh")
    def refresh(request: Request) -> Response:
        settings = _settings(request)
        if not settings.gate_enabled():
            return JSONResponse({"ok": True, "auth": "disabled"})
        username = try_refresh_username(request, settings)
        if not username:
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            clear_auth_cookies(response, settings)
            return response
        request.session[ADMIN_SESSION_KEY] = True
        response = JSONResponse({"ok": True})
        set_auth_cookies(response, settings, username)
        return response

    return router
