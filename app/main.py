"""RABOTA_APPLY monolith entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.application.services import AppService
from app.infrastructure.browser.job_runner import JobRunner
from app.infrastructure.browser.launch import sanitize_playwright_browsers_path
from app.infrastructure.browser.remote_session import RemoteBrowserManager
from app.infrastructure.db import create_uow
from app.infrastructure.scheduler import ParseScheduler, ReportScheduler
from app.infrastructure.settings import get_settings
from app.interfaces.admin import create_admin_router
from app.interfaces.api import create_api_router
from app.interfaces.api.reports_routes import create_reports_router

# Avoid Cursor sandbox PLAYWRIGHT_BROWSERS_PATH (wrong arch / incomplete cache)
sanitize_playwright_browsers_path()

WEB_DIR = Path(__file__).resolve().parent / "interfaces" / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_dirs()
    uow = create_uow(settings)
    runner = JobRunner(uow, settings)
    remote_browser = RemoteBrowserManager(uow, settings)
    scheduler = ReportScheduler(uow, settings)
    parse_scheduler = ParseScheduler(uow, settings, runner)
    service = AppService(
        uow, settings, runner, remote_browser, scheduler, parse_scheduler
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.report_schedule_enabled:
            scheduler.start()
        if settings.parse_schedule_enabled:
            parse_scheduler.start()
        yield
        await parse_scheduler.stop()
        await scheduler.stop()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.uow = uow
    app.state.runner = runner
    app.state.remote_browser = remote_browser
    app.state.scheduler = scheduler
    app.state.parse_scheduler = parse_scheduler
    app.state.service = service

    # Signed cookie sessions for /admin (only useful when ADMIN_USER/PASSWORD set)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret(),
        session_cookie="aa_admin_session",
        same_site="lax",
        https_only=False,
        max_age=60 * 60 * 12,
    )

    app.include_router(create_api_router())
    app.include_router(create_reports_router())
    app.include_router(create_admin_router())
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"app_name": settings.app_name},
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
