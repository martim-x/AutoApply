"""FastAPI business routes (ручки)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field


class ProfileBody(BaseModel):
    profile: str = Field(default="default", min_length=1, max_length=64)


class NewProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class RenameProfileBody(BaseModel):
    new_name: str = Field(min_length=1, max_length=64)


class RenameProfilePostBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    new_name: str = Field(min_length=1, max_length=64)


class RemoteStopBody(BaseModel):
    profile: str = Field(default="default", min_length=1, max_length=64)
    save: bool = True
    workspace: str | None = Field(default=None, max_length=32)


class StopBody(BaseModel):
    profile: str = Field(default="default", min_length=1, max_length=64)
    workspace: str | None = Field(default=None, max_length=32)


class LaunchTextBody(BaseModel):
    text: str = Field(min_length=1)


class LaunchJsonBody(BaseModel):
    launch: dict[str, Any]


class WorkspaceBody(BaseModel):
    profile: str = Field(default="default", min_length=1, max_length=64)
    workspace: str = Field(default="hh", max_length=32)


class LinkedInLaunchBody(BaseModel):
    launch: dict[str, Any]


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

    @router.get("/launch")
    def get_launch(request: Request) -> dict[str, Any]:
        return svc(request).get_launch()

    @router.post("/launch/validate")
    def validate_launch(body: LaunchTextBody, request: Request) -> dict[str, Any]:
        return svc(request).validate_launch_text(body.text)

    @router.post("/launch/text")
    def save_launch_text(body: LaunchTextBody, request: Request) -> dict[str, Any]:
        return svc(request).save_launch_from_text(body.text)

    @router.post("/launch/json")
    def save_launch_json(body: LaunchJsonBody, request: Request) -> dict[str, Any]:
        return svc(request).save_launch_from_json(body.launch)

    @router.get("/profiles")
    def profiles(request: Request) -> dict[str, Any]:
        return {"profiles": svc(request).list_profiles()}

    @router.post("/profiles")
    def create_profile(body: NewProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).ensure_profile(body.name)

    @router.patch("/profiles/{name}")
    def rename_profile(
        name: str, body: RenameProfileBody, request: Request
    ) -> dict[str, Any]:
        result = svc(request).rename_profile(name, body.new_name)
        if not result.get("ok"):
            raise HTTPException(
                status_code=400, detail=result.get("error") or "rename failed"
            )
        return result

    @router.post("/profiles/rename")
    def rename_profile_post(
        body: RenameProfilePostBody, request: Request
    ) -> dict[str, Any]:
        result = svc(request).rename_profile(body.name, body.new_name)
        if not result.get("ok"):
            raise HTTPException(
                status_code=400, detail=result.get("error") or "rename failed"
            )
        return result

    @router.delete("/profiles/{name}")
    def delete_profile(name: str, request: Request) -> dict[str, Any]:
        result = svc(request).delete_profile(name)
        if not result.get("ok"):
            raise HTTPException(
                status_code=400, detail=result.get("error") or "delete failed"
            )
        return result

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
        limit: int = Query(default=100, ge=1, le=10_000),
    ) -> dict[str, Any]:
        return {"vacancies": svc(request).list_vacancies(profile, limit=limit)}

    @router.get("/vacancies/explain")
    def vacancy_explain(
        request: Request,
        profile: str = Query(default="default"),
        vacancy_id: int | None = Query(default=None),
        url: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return svc(request).explain_vacancy(profile, vacancy_id=vacancy_id, url=url)

    @router.get("/logs")
    def logs(
        request: Request,
        profile: str = Query(default="default"),
        limit: int = Query(default=10_000, ge=1, le=100_000),
        service: str | None = Query(default=None),
    ) -> dict[str, Any]:
        journal_service = (service or "").strip().lower() or None
        if journal_service and journal_service not in ("hh", "linkedin"):
            raise HTTPException(
                status_code=400, detail="service must be hh or linkedin"
            )
        return {
            "logs": svc(request).recent_logs(
                profile, limit=limit, service=journal_service
            ),
            "service": journal_service,
        }

    @router.post("/login")
    def login(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_login(body.profile)

    @router.post("/login/confirm")
    def login_confirm(body: WorkspaceBody, request: Request) -> dict[str, Any]:
        return svc(request).confirm_login(body.profile, workspace=body.workspace)

    @router.post("/search")
    def search(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_search(body.profile)

    @router.post("/apply")
    def apply(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_apply(body.profile)

    @router.post("/stop")
    def stop(body: StopBody, request: Request) -> dict[str, Any]:
        return svc(request).stop_job(body.profile, workspace=body.workspace)

    # ── Remote interactive browser (CDP screencast) ────────────

    @router.get("/remote-browser/status")
    def remote_browser_status(
        request: Request,
        profile: str = Query(default="default"),
        workspace: str = Query(default="hh"),
    ) -> dict[str, Any]:
        return svc(request).remote_browser_status(profile, workspace=workspace)

    @router.post("/remote-browser/start")
    def remote_browser_start(body: WorkspaceBody, request: Request) -> dict[str, Any]:
        return svc(request).start_remote_browser(body.profile, workspace=body.workspace)

    @router.post("/remote-browser/save")
    def remote_browser_save(body: WorkspaceBody, request: Request) -> dict[str, Any]:
        return svc(request).save_remote_browser(body.profile, workspace=body.workspace)

    @router.post("/remote-browser/stop")
    def remote_browser_stop(body: RemoteStopBody, request: Request) -> dict[str, Any]:
        return svc(request).stop_remote_browser(
            body.profile, save=body.save, workspace=body.workspace
        )

    # ── LinkedIn workspace ────────────────────────────────────

    @router.get("/linkedin/launch")
    def linkedin_launch_get(request: Request) -> dict[str, Any]:
        return svc(request).get_linkedin_launch()

    @router.post("/linkedin/launch")
    def linkedin_launch_save(
        body: LinkedInLaunchBody, request: Request
    ) -> dict[str, Any]:
        return svc(request).save_linkedin_launch(body.launch)

    @router.post("/linkedin/launch/validate")
    def linkedin_launch_validate(
        body: LinkedInLaunchBody, request: Request
    ) -> dict[str, Any]:
        return svc(request).validate_linkedin_launch(body.launch)

    @router.post("/linkedin/login")
    def linkedin_login(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_linkedin_login(body.profile)

    @router.post("/linkedin/network")
    def linkedin_network(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_linkedin_network(body.profile)

    @router.post("/linkedin/vacancies/search")
    def linkedin_vacancies_search(
        body: ProfileBody, request: Request
    ) -> dict[str, Any]:
        return svc(request).start_linkedin_vacancies(body.profile)

    @router.get("/linkedin/contacts")
    def linkedin_contacts(
        request: Request,
        profile: str = Query(default="default"),
        limit: int = Query(default=100, ge=1, le=10_000),
    ) -> dict[str, Any]:
        return {"contacts": svc(request).list_linkedin_contacts(profile, limit=limit)}

    @router.get("/linkedin/vacancies")
    def linkedin_vacancies(
        request: Request,
        profile: str = Query(default="default"),
        limit: int = Query(default=100, ge=1, le=10_000),
    ) -> dict[str, Any]:
        return {"vacancies": svc(request).list_linkedin_vacancies(profile, limit=limit)}

    @router.websocket("/remote-browser/ws")
    async def remote_browser_ws(
        websocket: WebSocket,
        profile: str = Query(default="default"),
        workspace: str = Query(default="hh"),
    ) -> None:
        """Stream JPEG screencast frames; accept mouse/keyboard JSON commands."""
        await websocket.accept()
        service = websocket.app.state.service
        manager = websocket.app.state.remote_browser
        profile = (profile or "default").strip() or "default"
        from app.infrastructure.browser.workspace import normalize_workspace

        ws_name = normalize_workspace(workspace)

        if not manager.enabled():
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "remote browser disabled (ENABLE_REMOTE_BROWSER=true)",
                }
            )
            await websocket.close()
            return

        sess = manager.get(profile, ws_name)
        if not sess:
            result = await asyncio.to_thread(
                service.start_remote_browser, profile, workspace=ws_name
            )
            if not result.get("ok"):
                await websocket.send_json(
                    {"type": "error", "error": result.get("error") or "start failed"}
                )
                await websocket.close()
                return
            sess = manager.get(profile, ws_name)
        if not sess:
            await websocket.send_json({"type": "error", "error": "session missing"})
            await websocket.close()
            return

        await websocket.send_json(
            {
                "type": "hello",
                "profile": profile,
                "workspace": ws_name,
                "viewport": {"width": 1280, "height": 900},
                "url": sess.url,
            }
        )

        stop = asyncio.Event()

        async def pump_frames() -> None:
            try:
                while not stop.is_set():
                    frame = await asyncio.to_thread(sess.get_frame, 0.4)
                    if frame is None:
                        if not sess.alive:
                            await websocket.send_json(
                                {"type": "closed", "message": "browser stopped"}
                            )
                            break
                        continue
                    await websocket.send_json(frame)
            except Exception:
                pass
            finally:
                stop.set()

        async def pump_input() -> None:
            try:
                while not stop.is_set():
                    msg = await websocket.receive_json()
                    if not isinstance(msg, dict):
                        continue
                    kind = msg.get("type")
                    if kind == "ping":
                        await websocket.send_json({"type": "pong"})
                        continue
                    if kind in ("mouse", "key", "navigate", "save", "stop"):
                        sess.push_cmd(msg)
                        if kind == "stop":
                            break
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                stop.set()

        try:
            await asyncio.gather(pump_frames(), pump_input())
        finally:
            stop.set()

    return router
