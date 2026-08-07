"""Tests for HH / LinkedIn workspace session path resolution."""

from __future__ import annotations

from pathlib import Path

from app.infrastructure.browser.workspace import (
    browser_slot_key,
    normalize_workspace,
    storage_state_path,
)
from app.infrastructure.settings import Settings


def test_normalize_workspace():
    assert normalize_workspace("hh") == "hh"
    assert normalize_workspace("linkedin") == "linkedin"
    assert normalize_workspace("LINKEDIN") == "linkedin"
    assert normalize_workspace(None) == "hh"
    assert normalize_workspace("other") == "hh"


def test_browser_slot_key_independent_per_workspace():
    assert browser_slot_key("default", "hh") == "default:hh"
    assert browser_slot_key("default", "linkedin") == "default:linkedin"
    assert browser_slot_key("default", "hh") != browser_slot_key(
        "default", "linkedin"
    )
    assert browser_slot_key(" alice ", "linkedin") == "alice:linkedin"


def test_storage_state_path_per_workspace(tmp_path: Path):
    s = Settings(
        data_dir=tmp_path,
        sessions_dir=tmp_path / "sessions",
        enable_remote_browser=False,
    )
    hh = storage_state_path(s, "tim", "hh")
    li = storage_state_path(s, "tim", "linkedin")
    assert hh.name == "tim.storage.json"
    assert li.name == "tim.linkedin.storage.json"
    assert hh != li
    assert hh.parent == li.parent
    assert s.state_path("tim") == hh
    assert s.linkedin_state_path("tim") == li


def test_remote_manager_keys_are_workspace_scoped(tmp_path: Path):
    """Manager registry can hold two slots conceptually (key helper)."""
    from app.infrastructure.browser.remote_session import RemoteBrowserManager
    from app.infrastructure.db.sqlite_uow import SqliteUnitOfWork

    uow = SqliteUnitOfWork(tmp_path / "t.sqlite")
    settings = Settings(
        data_dir=tmp_path,
        sessions_dir=tmp_path / "sessions",
        enable_remote_browser=True,
    )
    mgr = RemoteBrowserManager(uow, settings)
    assert mgr.get("default", "hh") is None
    assert mgr.get("default", "linkedin") is None
    assert mgr.any_running("default") is False
    st = mgr.status_all("default")
    assert st["hh"]["running"] is False
    assert st["linkedin"]["running"] is False
    assert st["hh"]["workspace"] == "hh"
    assert st["linkedin"]["workspace"] == "linkedin"
