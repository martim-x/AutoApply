"""FastAPI business routes (ручки)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field


class ProfileBody(BaseModel):
    profile: str = Field(default="default", min_length=1, max_length=64)


class NewProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


def create_api_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["api"])

    def svc(request: Request):
        return request.app.state.service

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/config")
    def config(request: Request) -> dict[str, Any]:
        return svc(request).config_public()

    @router.get("/profiles")
    def profiles(request: Request) -> dict[str, Any]:
        return {"profiles": svc(request).list_profiles()}

    @router.post("/profiles")
    def create_profile(body: NewProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).ensure_profile(body.name)

    @router.get("/status")
    def status(
        request: Request,
        profile: str = Query(default="default"),
    ) -> dict[str, Any]:
        return svc(request).get_status(profile)

    @router.get("/stats")
    def stats(
        request: Request,
        profile: str = Query(default="default"),
    ) -> dict[str, Any]:
        return svc(request).get_stats(profile)

    @router.get("/vacancies")
    def vacancies(
        request: Request,
        profile: str = Query(default="default"),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return {"vacancies": svc(request).list_vacancies(profile, limit=limit)}

    @router.get("/logs")
    def logs(
        request: Request,
        profile: str = Query(default="default"),
        limit: int = Query(default=60, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"logs": svc(request).recent_logs(profile, limit=limit)}

    @router.post("/login")
    def login(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_login(body.profile)

    @router.post("/login/confirm")
    def login_confirm(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).confirm_login(body.profile)

    @router.post("/search")
    def search(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_search(body.profile)

    @router.post("/apply")
    def apply(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_apply(body.profile)

    @router.post("/stop")
    def stop(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).stop_job(body.profile)

    return router
