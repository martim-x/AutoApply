"""Admin /admin gate and .env editor."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.infrastructure import settings as settings_mod
from app.main import create_app


@pytest.fixture
def admin_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("HEADLESS=true\nFOO=bar\n", encoding="utf-8")
    monkeypatch.setattr(settings_mod, "ROOT", tmp_path)
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("ADMIN_SECRET", "test-admin-secret-key")
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data / 't.sqlite'}")
    settings_mod.get_settings.cache_clear()
    yield tmp_path
    settings_mod.get_settings.cache_clear()


@pytest.fixture
def disabled_admin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings_mod, "ROOT", tmp_path)
    monkeypatch.delenv("ADMIN_USER", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_USER", "")
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data / 't.sqlite'}")
    settings_mod.get_settings.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()


def test_admin_disabled_404(disabled_admin):
    client = TestClient(create_app())
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/login").status_code == 404


def test_admin_login_and_save_env(admin_env: Path):
    client = TestClient(create_app())

    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "Admin" in r.text

    bad = client.post(
        "/admin/login",
        data={"name": "admin", "password": "wrong"},
    )
    assert bad.status_code == 401

    ok = client.post(
        "/admin/login",
        data={"name": "admin", "password": "s3cret"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/admin/env"

    page = client.get("/admin/env")
    assert page.status_code == 200
    assert "FOO=bar" in page.text

    saved = client.post(
        "/admin/env",
        data={"content": "HEADLESS=true\nFOO=baz\n"},
    )
    assert saved.status_code == 200
    assert "Сохранено" in saved.text
    assert (admin_env / ".env").read_text(encoding="utf-8") == "HEADLESS=true\nFOO=baz\n"


def test_admin_env_requires_auth(admin_env: Path):
    client = TestClient(create_app())
    r = client.get("/admin/env", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
