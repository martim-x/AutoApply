"""ASGI middleware: require owner gate cookies (or admin session) for app routes."""

from __future__ import annotations

from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.infrastructure.gate_auth import (
    ACCESS_COOKIE,
    ACCESS_MAX_AGE,
    ADMIN_SESSION_KEY,
    cookie_secure,
    issue_access_token,
    try_refresh_username,
    username_from_request,
    verify_access_token,
)

PUBLIC_EXACT = frozenset(
    {
        "/login",
        "/logout",
        "/api/health",
        "/api/auth/refresh",
        "/favicon.ico",
    }
)


def _is_public(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    if path.startswith("/static/"):
        return True
    if path == "/static":
        return True
    # Admin panel has its own login; leave it alone.
    if path == "/admin" or path.startswith("/admin/"):
        return True
    return False


def _wants_json(scope: Scope) -> bool:
    path = scope.get("path") or ""
    if path.startswith("/api/"):
        return True
    headers = Headers(scope=scope)
    accept = headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


class GateAuthMiddleware:
    """Protect HTML + API + WebSocket when gate credentials are configured."""

    def __init__(self, app: ASGIApp, settings: Any) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        asgi_app = scope.get("app")
        state = getattr(asgi_app, "state", None) if asgi_app is not None else None
        settings = getattr(state, "settings", None) or self.settings

        if not settings.gate_enabled():
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if _is_public(path):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        user = username_from_request(request, settings)
        refreshed: str | None = None

        if user is None:
            # Access missing/expired — try refresh cookie once.
            access = request.cookies.get(ACCESS_COOKIE)
            access_still_valid = bool(
                access and verify_access_token(settings.auth_secret(), access)
            )
            if not access_still_valid:
                refreshed = try_refresh_username(request, settings)
                if refreshed:
                    user = refreshed

        if user is None:
            await self._deny(scope, receive, send)
            return

        if refreshed and scope["type"] == "http":
            await self._call_with_access_cookie(
                scope, receive, send, settings, refreshed
            )
            return

        await self.app(scope, receive, send)

    async def _deny(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        if _wants_json(scope):
            response: Response = JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
            )
        else:
            response = RedirectResponse(url="/login", status_code=303)
        await response(scope, receive, send)

    async def _call_with_access_cookie(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        settings: Any,
        username: str,
    ) -> None:
        token = issue_access_token(settings.auth_secret(), username)
        secure = cookie_secure(settings)
        cookie = (
            f"{ACCESS_COOKIE}={token}; Path=/; Max-Age={ACCESS_MAX_AGE}; "
            f"HttpOnly; SameSite=Lax"
        )
        if secure:
            cookie += "; Secure"

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("Set-Cookie", cookie)
            await send(message)

        # Keep admin session in sync when refreshing via cookies only.
        # Session is already loaded by SessionMiddleware; mutate if present.
        session = scope.get("session")
        if isinstance(session, dict):
            session[ADMIN_SESSION_KEY] = True

        await self.app(scope, receive, send_wrapper)
