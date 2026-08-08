"""PDF report download routes (separate from main API router)."""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.application.reports import REPORT_KINDS, assemble_report, normalize_kind
from app.infrastructure.reports.pdf import iter_file_chunks, render_report_pdf

ReportKindLiteral = Literal["work", "queue", "launch", "linkedin"]


class GenerateReportBody(BaseModel):
    kind: ReportKindLiteral = "work"
    profile: str = Field(default="default", min_length=1, max_length=64)
    # When true, also email HTML + PDF via ALERT_SMTP_* (scheduled path always tries).
    email: bool = False


def create_reports_router() -> APIRouter:
    router = APIRouter(prefix="/api/reports", tags=["reports"])

    def _stream(request: Request, kind: str, profile: str) -> StreamingResponse:
        try:
            kind = normalize_kind(kind)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        profile = (profile or "default").strip() or "default"
        service = request.app.state.service
        try:
            payload = assemble_report(service.uow, service.settings, kind, profile)
            path = render_report_pdf(payload)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"report generation failed: {e}"
            ) from e

        filename = f"auto-apply-app-{kind}-{profile}.pdf"

        def _cleanup() -> None:
            try:
                os.unlink(path)
            except OSError:
                pass

        return StreamingResponse(
            iter_file_chunks(path),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
            background=BackgroundTask(_cleanup),
        )

    @router.get("")
    def list_kinds(request: Request) -> dict[str, Any]:
        service = request.app.state.service
        files = service.list_report_files(limit=30)
        sched = (
            service.scheduler.status()
            if getattr(service, "scheduler", None)
            else service.settings.parse_report_schedule()
        )
        return {
            "kinds": list(REPORT_KINDS),
            "files": files,
            "schedule": sched,
            "endpoints": {
                "download": "GET /api/reports/{kind}.pdf?profile=default",
                "generate": "POST /api/reports/generate",
                "save": "POST /api/reports/save",
            },
        }

    @router.post("/save")
    def save_report(body: GenerateReportBody, request: Request) -> dict[str, Any]:
        """Generate PDF into data/reports/ (kept on disk); optional email."""
        service = request.app.state.service
        try:
            return service.run_report_now(
                kind=body.kind,
                profile=body.profile,
                scheduled=False,
                email=body.email,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    @router.get("/{kind}.pdf")
    def download_pdf(
        kind: str,
        request: Request,
        profile: str = Query(default="default"),
    ) -> StreamingResponse:
        return _stream(request, kind, profile)

    @router.post("/generate")
    def generate_pdf(body: GenerateReportBody, request: Request) -> StreamingResponse:
        return _stream(request, body.kind, body.profile)

    return router
