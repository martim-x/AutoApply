"""HH vs LinkedIn workspace helpers (session / job slot keys)."""

from __future__ import annotations

from pathlib import Path

from app.infrastructure.settings import Settings

WORKSPACES = frozenset({"hh", "linkedin"})


def normalize_workspace(workspace: str | None) -> str:
    ws = (workspace or "hh").strip().lower()
    return ws if ws in WORKSPACES else "hh"


def browser_slot_key(profile: str, workspace: str | None = "hh") -> str:
    """Registry key: one remote browser / job thread per profile×workspace."""
    return f"{(profile or 'default').strip() or 'default'}:{normalize_workspace(workspace)}"


def storage_state_path(
    settings: Settings, profile: str, workspace: str | None = "hh"
) -> Path:
    """Cookie / storage_state file for profile×workspace."""
    if normalize_workspace(workspace) == "linkedin":
        return settings.linkedin_state_path(profile)
    return settings.state_path(profile)
