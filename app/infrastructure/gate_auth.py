"""Cookie-based owner gate: short-lived access JWT + longer refresh JWT."""

from __future__ import annotations

import hmac
import time
from typing import Any

import jwt
from starlette.requests import Request
from starlette.responses import Response

ACCESS_COOKIE = "nexus_token"
REFRESH_COOKIE = "refresh_token"
ACCESS_MAX_AGE = 15 * 60  # 15 minutes
REFRESH_MAX_AGE = 14 * 24 * 60 * 60  # 14 days
ADMIN_SESSION_KEY = "admin_authed"
JWT_ALG = "HS256"


def const_eq(left: str, right: str) -> bool:
    """Constant-time compare; False when lengths differ (compare_digest raises)."""
    a = left.encode("utf-8")
    b = right.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def _encode(secret: str, *, username: str, token_type: str, max_age: int) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "typ": token_type,
        "iat": now,
        "exp": now + int(max_age),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALG)


def _decode_username(
    secret: str,
    token: str,
    *,
    expected_type: str,
) -> str | None:
    try:
        data = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALG],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if not isinstance(data, dict) or data.get("typ") != expected_type:
        return None
    sub = data.get("sub")
    return str(sub) if sub else None


def issue_access_token(secret: str, username: str) -> str:
    return _encode(secret, username=username, token_type="access", max_age=ACCESS_MAX_AGE)


def issue_refresh_token(secret: str, username: str) -> str:
    return _encode(
        secret, username=username, token_type="refresh", max_age=REFRESH_MAX_AGE
    )


def verify_access_token(
    secret: str,
    token: str,
    max_age: int = ACCESS_MAX_AGE,  # noqa: ARG001 — kept for call-site compat
) -> str | None:
    return _decode_username(secret, token, expected_type="access")


def verify_refresh_token(
    secret: str,
    token: str,
    max_age: int = REFRESH_MAX_AGE,  # noqa: ARG001 — kept for call-site compat
) -> str | None:
    return _decode_username(secret, token, expected_type="refresh")


def cookie_secure(settings: Any) -> bool:
    return bool(getattr(settings, "auth_cookie_secure", False))


def set_auth_cookies(response: Response, settings: Any, username: str) -> None:
    secret = settings.auth_secret()
    secure = cookie_secure(settings)
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=issue_access_token(secret, username),
        max_age=ACCESS_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=issue_refresh_token(secret, username),
        max_age=REFRESH_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_auth_cookies(response: Response, settings: Any) -> None:
    """Expire access + refresh JWTs (match Path/SameSite; cover Secure mismatch)."""
    secure = cookie_secure(settings)
    # Primary clear with the same flags used at set time.
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(
            key=name,
            path="/",
            httponly=True,
            samesite="lax",
            secure=secure,
        )
    # Extra expires if Secure flag previously mismatched the current setting.
    if secure:
        for name in (ACCESS_COOKIE, REFRESH_COOKIE):
            response.delete_cookie(
                key=name,
                path="/",
                httponly=True,
                samesite="lax",
                secure=False,
            )
    else:
        for name in (ACCESS_COOKIE, REFRESH_COOKIE):
            response.delete_cookie(
                key=name,
                path="/",
                httponly=True,
                samesite="lax",
                secure=True,
            )


def username_from_request(request: Request, settings: Any) -> str | None:
    """Resolve authenticated username from access JWT cookie only."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        return None
    return verify_access_token(settings.auth_secret(), token)


def try_refresh_username(request: Request, settings: Any) -> str | None:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        return None
    return verify_refresh_token(settings.auth_secret(), token)
