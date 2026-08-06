"""FastAPI business routes (ручки)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field


class ProfileBody(BaseModel):
    profile: str = Field(default="default", min_length=1, max_length=64)


class NewProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class RemoteStopBody(BaseModel):
    profile: str = Field(default="default", min_length=1, max_length=64)
    save: bool = True


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

    @router.get("/vacancies/explain")
    def vacancy_explain(
        request: Request,
        profile: str = Query(default="default"),
        vacancy_id: int | None = Query(default=None),
        url: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return svc(request).explain_vacancy(
            profile, vacancy_id=vacancy_id, url=url
        )

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

    # ── Remote interactive browser (CDP screencast) ────────────

    @router.get("/remote-browser/status")
    def remote_browser_status(
        request: Request,
        profile: str = Query(default="default"),
    ) -> dict[str, Any]:
        return svc(request).remote_browser_status(profile)

    @router.post("/remote-browser/start")
    def remote_browser_start(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).start_remote_browser(body.profile)

    @router.post("/remote-browser/save")
    def remote_browser_save(body: ProfileBody, request: Request) -> dict[str, Any]:
        return svc(request).save_remote_browser(body.profile)

    @router.post("/remote-browser/stop")
    def remote_browser_stop(body: RemoteStopBody, request: Request) -> dict[str, Any]:
        return svc(request).stop_remote_browser(body.profile, save=body.save)

    @router.websocket("/remote-browser/ws")
    async def remote_browser_ws(
        websocket: WebSocket,
        profile: str = Query(default="default"),
    ) -> None:
        """Stream JPEG screencast frames; accept mouse/keyboard JSON commands."""
        await websocket.accept()
        service = websocket.app.state.service
        manager = websocket.app.state.remote_browser
        profile = (profile or "default").strip() or "default"

        if not manager.enabled():
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "remote browser disabled (ENABLE_REMOTE_BROWSER=true)",
                }
            )
            await websocket.close()
            return

        sess = manager.get(profile)
        if not sess:
            result = await asyncio.to_thread(service.start_remote_browser, profile)
            if not result.get("ok"):
                await websocket.send_json(
                    {"type": "error", "error": result.get("error") or "start failed"}
                )
                await websocket.close()
                return
            sess = manager.get(profile)
        if not sess:
            await websocket.send_json({"type": "error", "error": "session missing"})
            await websocket.close()
            return

        await websocket.send_json(
            {
                "type": "hello",
                "profile": profile,
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
