"""RABOTA_APPLY monolith entrypoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.application.services import AppService
from app.infrastructure.browser.job_runner import JobRunner
from app.infrastructure.db import create_uow
from app.infrastructure.settings import get_settings
from app.interfaces.api import create_api_router

WEB_DIR = Path(__file__).resolve().parent / "interfaces" / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_dirs()
    uow = create_uow(settings)
    runner = JobRunner(uow, settings)
    service = AppService(uow, settings, runner)

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    app.state.uow = uow
    app.state.runner = runner
    app.state.service = service

    app.include_router(create_api_router())
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
