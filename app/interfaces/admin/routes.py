"""Password-gated admin UI to view/edit project .env."""

from __future__ import annotations

import hmac
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER, HTTP_404_NOT_FOUND

from app.infrastructure import settings as settings_mod
from app.infrastructure.settings import get_settings

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

SESSION_KEY = "admin_authed"


def _env_path() -> Path:
    return settings_mod.ROOT / ".env"


def create_admin_router() -> APIRouter:
    router = APIRouter(tags=["admin"])

    def _settings():
        return get_settings()

    def _enabled(request: Request) -> bool:
        settings = getattr(request.app.state, "settings", None) or _settings()
        return bool(settings.admin_enabled())

    def _authed(request: Request) -> bool:
        return bool(request.session.get(SESSION_KEY))

    def _require_enabled(request: Request) -> HTMLResponse | None:
        if not _enabled(request):
            return HTMLResponse("Not Found", status_code=HTTP_404_NOT_FOUND)
        return None

    def _login_redirect() -> RedirectResponse:
        return RedirectResponse(url="/admin/login", status_code=HTTP_303_SEE_OTHER)

    @router.get("/admin", response_class=HTMLResponse)
    def admin_index(request: Request) -> HTMLResponse:
        denied = _require_enabled(request)
        if denied:
            return denied
        if not _authed(request):
            return _login_redirect()
        return RedirectResponse(url="/admin/env", status_code=HTTP_303_SEE_OTHER)

    @router.get("/admin/login", response_class=HTMLResponse)
    def admin_login_get(request: Request) -> HTMLResponse:
        denied = _require_enabled(request)
        if denied:
            return denied
        if _authed(request):
            return RedirectResponse(url="/admin/env", status_code=HTTP_303_SEE_OTHER)
        settings = request.app.state.settings
        return TEMPLATES.TemplateResponse(
            request,
            "admin_login.html",
            {
                "app_name": settings.app_name,
                "error": None,
            },
        )

    @router.post("/admin/login", response_class=HTMLResponse)
    def admin_login_post(
        request: Request,
        name: str = Form(...),
        password: str = Form(...),
    ) -> HTMLResponse:
        denied = _require_enabled(request)
        if denied:
            return denied
        settings = request.app.state.settings
        expect_user = (settings.admin_user or "").strip()
        expect_pass = settings.admin_password or ""
        user_ok = _const_eq(name.strip(), expect_user)
        pass_ok = _const_eq(password, expect_pass)
        if not (user_ok and pass_ok):
            return TEMPLATES.TemplateResponse(
                request,
                "admin_login.html",
                {
                    "app_name": settings.app_name,
                    "error": "Неверный логин или пароль",
                },
                status_code=401,
            )
        request.session[SESSION_KEY] = True
        return RedirectResponse(url="/admin/env", status_code=HTTP_303_SEE_OTHER)

    @router.post("/admin/logout")
    def admin_logout(request: Request) -> HTMLResponse:
        denied = _require_enabled(request)
        if denied:
            return denied
        request.session.clear()
        return _login_redirect()

    @router.get("/admin/env", response_class=HTMLResponse)
    def admin_env_get(request: Request) -> HTMLResponse:
        denied = _require_enabled(request)
        if denied:
            return denied
        if not _authed(request):
            return _login_redirect()
        settings = request.app.state.settings
        content = _read_env_file()
        return TEMPLATES.TemplateResponse(
            request,
            "admin_env.html",
            {
                "app_name": settings.app_name,
                "env_content": content,
                "env_path": str(_env_path()),
                "message": None,
                "error": None,
            },
        )

    @router.post("/admin/env", response_class=HTMLResponse)
    def admin_env_post(
        request: Request,
        content: str = Form(""),
    ) -> HTMLResponse:
        denied = _require_enabled(request)
        if denied:
            return denied
        if not _authed(request):
            return _login_redirect()
        settings = request.app.state.settings
        try:
            _write_env_file(content)
            message = (
                "Сохранено. Перезапустите контейнер / процесс, "
                "чтобы применить изменения (часть настроек читается только при старте)."
            )
            error = None
            log.info("Admin saved .env (%s bytes)", len(content.encode("utf-8")))
        except OSError as exc:
            message = None
            error = f"Не удалось записать .env: {exc}"
            log.exception("Admin failed to write .env")
        return TEMPLATES.TemplateResponse(
            request,
            "admin_env.html",
            {
                "app_name": settings.app_name,
                "env_content": content,
                "env_path": str(_env_path()),
                "message": message,
                "error": error,
            },
            status_code=500 if error else 200,
        )

    return router


def _const_eq(left: str, right: str) -> bool:
    """Constant-time compare; False when lengths differ (compare_digest raises)."""
    a = left.encode("utf-8")
    b = right.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def _read_env_file() -> str:
    path = _env_path()
    if not path.is_file():
        example = settings_mod.ROOT / ".env.example"
        if example.is_file():
            return example.read_text(encoding="utf-8")
        return ""
    return path.read_text(encoding="utf-8")


def _write_env_file(content: str) -> None:
    """Atomic write of .env (temp file in same dir + replace)."""
    path = _env_path()
    text = content.replace("\r\n", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".env.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
