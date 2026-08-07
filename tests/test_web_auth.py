"""Owner gate: /login cookies and API protection."""

from __future__ import annotations

from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from app.infrastructure import settings as settings_mod
from app.infrastructure.gate_auth import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    issue_access_token,
    issue_refresh_token,
    verify_access_token,
    verify_refresh_token,
)
from app.main import create_app


@pytest.fixture
def gate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings_mod, "ROOT", tmp_path)
    monkeypatch.setenv("ADMIN_USER", "owner")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("ADMIN_SECRET", "test-gate-secret-key-32bytes-min!")
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data / 't.sqlite'}")
    settings_mod.get_settings.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()


@pytest.fixture
def open_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings_mod, "ROOT", tmp_path)
    monkeypatch.delenv("ADMIN_USER", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("GATE_USER", raising=False)
    monkeypatch.delenv("GATE_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_USER", "")
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    monkeypatch.setenv("GATE_USER", "")
    monkeypatch.setenv("GATE_PASSWORD", "")
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data / 't.sqlite'}")
    settings_mod.get_settings.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()


def test_tokens_are_jwt():
    secret = "test-gate-secret-key-32bytes-min!"
    access = issue_access_token(secret, "owner")
    refresh = issue_refresh_token(secret, "owner")
    assert access.count(".") == 2
    assert refresh.count(".") == 2
    access_payload = jwt.decode(access, secret, algorithms=["HS256"])
    refresh_payload = jwt.decode(refresh, secret, algorithms=["HS256"])
    assert access_payload["typ"] == "access"
    assert refresh_payload["typ"] == "refresh"
    assert access_payload["sub"] == "owner"
    assert "exp" in access_payload and "iat" in access_payload
    assert verify_access_token(secret, access) == "owner"
    assert verify_refresh_token(secret, refresh) == "owner"
    assert verify_access_token(secret, refresh) is None
    assert verify_refresh_token(secret, access) is None


def test_gate_disabled_allows_app(open_env):
    client = TestClient(create_app())
    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/config").status_code == 200


def test_unauthenticated_html_redirects_to_login(gate_env):
    client = TestClient(create_app())
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_unauthenticated_api_returns_401(gate_env):
    client = TestClient(create_app())
    r = client.get("/api/config")
    assert r.status_code == 401
    assert r.json()["detail"] == "Unauthorized"


def test_health_public_when_gate_enabled(gate_env):
    client = TestClient(create_app())
    assert client.get("/api/health").status_code == 200


def test_login_page_ok(gate_env):
    client = TestClient(create_app())
    r = client.get("/login")
    assert r.status_code == 200
    assert "auto-apply-app" in r.text or "name" in r.text


def test_login_bad_password(gate_env):
    client = TestClient(create_app())
    bad = client.post(
        "/login",
        data={"name": "owner", "password": "wrong"},
    )
    assert bad.status_code == 401
    assert ACCESS_COOKIE not in bad.cookies


def test_login_success_sets_cookies_and_opens_app(gate_env):
    client = TestClient(create_app())
    ok = client.post(
        "/login",
        data={"name": "owner", "password": "s3cret"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/"
    assert ACCESS_COOKIE in ok.cookies
    assert REFRESH_COOKIE in ok.cookies
    # Cookies must be real JWTs
    assert ok.cookies[ACCESS_COOKIE].count(".") == 2

    home = client.get("/")
    assert home.status_code == 200

    api = client.get("/api/config")
    assert api.status_code == 200


def test_logout_clears_access(gate_env):
    client = TestClient(create_app())
    client.post("/login", data={"name": "owner", "password": "s3cret"})
    out = client.post("/logout", follow_redirects=False)
    assert out.status_code == 303
    assert out.headers["location"] == "/login"
    denied = client.get("/api/config")
    assert denied.status_code == 401
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/login"


def test_logout_get_also_works(gate_env):
    client = TestClient(create_app())
    client.post("/login", data={"name": "owner", "password": "s3cret"})
    out = client.get("/logout", follow_redirects=False)
    assert out.status_code == 303
    assert out.headers["location"] == "/login"
    assert client.get("/api/config").status_code == 401


def test_session_alone_does_not_authenticate(gate_env):
    """Gate requires JWT cookies; admin session cookie is not enough."""
    client = TestClient(create_app())
    client.post("/login", data={"name": "owner", "password": "s3cret"})
    # Drop JWT cookies but keep whatever session jar had
    client.cookies.delete(ACCESS_COOKIE)
    client.cookies.delete(REFRESH_COOKIE)
    assert client.get("/api/config").status_code == 401


def test_refresh_endpoint_reissues_cookies(gate_env):
    client = TestClient(create_app())
    client.post("/login", data={"name": "owner", "password": "s3cret"})
    # Drop access cookie; keep refresh via client jar + re-set refresh only
    client.cookies.clear()
    secret = "test-gate-secret-key-32bytes-min!"
    client.cookies.set(REFRESH_COOKIE, issue_refresh_token(secret, "owner"))
    r = client.post("/api/auth/refresh")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert ACCESS_COOKIE in r.cookies


def test_middleware_auto_refresh_from_refresh_cookie(gate_env):
    client = TestClient(create_app())
    client.cookies.set(
        REFRESH_COOKIE,
        issue_refresh_token("test-gate-secret-key-32bytes-min!", "owner"),
    )
    r = client.get("/api/config")
    assert r.status_code == 200


def test_websocket_rejected_without_auth(gate_env):
    """WebSocket must not crash with AssertionError; close unauthorized."""
    client = TestClient(create_app())
    with pytest.raises(Exception):
        with client.websocket_connect("/api/remote-browser/ws?profile=default"):
            pass


def test_websocket_accepts_with_access_cookie(gate_env, monkeypatch: pytest.MonkeyPatch):
    """Regression: Request(scope) must not be used for websocket auth."""
    monkeypatch.setenv("ENABLE_REMOTE_BROWSER", "false")
    settings_mod.get_settings.cache_clear()
    client = TestClient(create_app())
    client.post("/login", data={"name": "owner", "password": "s3cret"})
    with client.websocket_connect("/api/remote-browser/ws?profile=default") as ws:
        msg = ws.receive_json()
        assert msg.get("type") == "error"
        assert "remote browser disabled" in (msg.get("error") or "").lower()
