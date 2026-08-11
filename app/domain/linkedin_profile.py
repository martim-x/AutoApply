"""LinkedIn launch / search preferences (browser automation only — no official API)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.config_defaults import ConfigLoadResult, deep_merge_defaults

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LINKEDIN_LAUNCH_PATH = ROOT / "data" / "config" / "linkedin.launch.json"
EXAMPLE_LINKEDIN_LAUNCH_PATH = ROOT / "config" / "linkedin.launch.example.json"

LINKEDIN_BASE = "https://www.linkedin.com"
LINKEDIN_LOGIN = f"{LINKEDIN_BASE}/login"

# Documented defaults when config keys are missing (do not crash).
LINKEDIN_LAUNCH_DEFAULTS: dict[str, Any] = {
    "locations": ["Minsk", "Russia", "CIS"],
    "people_queries": ["HR", "backend developer", "Python backend"],
    "vacancy_queries": [
        "Python backend",
        "Backend developer",
        "Python developer",
    ],
    "connect_limit": 15,
    "vacancy_limit": 40,
    "max_profiles_per_query": 10,
    "min_action_interval": 8.0,
    "after_connect_delay": 14.0,
    "jitter": 0.4,
    "dry_run": False,
    "note": (
        "Browser automation only. Aggressive use may trigger LinkedIn "
        "restrictions — keep limits conservative."
    ),
}


class LinkedInLaunchProfile(BaseModel):
    """Параметры LinkedIn networking + vacancy scrape (config/linkedin.launch.json)."""

    locations: list[str] = Field(
        default_factory=lambda: list(LINKEDIN_LAUNCH_DEFAULTS["locations"])
    )
    people_queries: list[str] = Field(
        default_factory=lambda: list(LINKEDIN_LAUNCH_DEFAULTS["people_queries"])
    )
    vacancy_queries: list[str] = Field(
        default_factory=lambda: list(LINKEDIN_LAUNCH_DEFAULTS["vacancy_queries"])
    )
    connect_limit: int = Field(default=15, ge=1, le=10_000)
    vacancy_limit: int = Field(default=40, ge=1, le=100_000)
    max_profiles_per_query: int = Field(default=10, ge=1, le=10_000)
    min_action_interval: float = Field(default=8.0, ge=3.0, le=120.0)
    after_connect_delay: float = Field(default=14.0, ge=5.0, le=180.0)
    jitter: float = Field(default=0.4, ge=0.0, le=1.0)
    dry_run: bool = False
    note: str = ""

    @field_validator(
        "locations",
        "people_queries",
        "vacancy_queries",
        mode="before",
    )
    @classmethod
    def _split_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            parts = [p.strip() for p in v.replace("\n", ",").split(",")]
        elif isinstance(v, list):
            parts = [str(p).strip() for p in v]
        else:
            raise ValueError("expected list or comma-separated string")
        out: list[str] = []
        seen: set[str] = set()
        for p in parts:
            if not p:
                continue
            key = p.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    def people_search_combos(self) -> list[tuple[str, str]]:
        """(query, location) pairs for people search."""
        locs = self.locations or ["Minsk"]
        queries = self.people_queries or ["HR"]
        return [(q, loc) for loc in locs for q in queries]

    def vacancy_search_combos(self) -> list[tuple[str, str]]:
        locs = self.locations or ["Minsk"]
        queries = self.vacancy_queries or ["Python backend"]
        return [(q, loc) for loc in locs for q in queries]

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump()


@lru_cache
def linkedin_defaults_public() -> dict[str, Any]:
    return dict(LINKEDIN_LAUNCH_DEFAULTS)


def validate_linkedin_dict(data: dict[str, Any]) -> LinkedInLaunchProfile:
    return LinkedInLaunchProfile.model_validate(data)


def load_linkedin_launch(
    path: Path | None = None,
) -> tuple[LinkedInLaunchProfile, ConfigLoadResult]:
    """
    Load LinkedIn launch config with soft defaults.
    Never raises for missing file / missing keys — applies defaults + notifications.
    """
    p = path or DEFAULT_LINKEDIN_LAUNCH_PATH
    raw: dict[str, Any] | None = None
    source = "defaults"
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            source = str(p)
        except (OSError, json.JSONDecodeError) as e:
            merged, notes = deep_merge_defaults(None, LINKEDIN_LAUNCH_DEFAULTS)
            notes.insert(0, f"linkedin launch unreadable ({e}); using defaults")
            profile = validate_linkedin_dict(merged)
            return profile, ConfigLoadResult(
                data=merged, notifications=notes, used_defaults=True, source="defaults"
            )
    elif EXAMPLE_LINKEDIN_LAUNCH_PATH.exists() and path is None:
        try:
            raw = json.loads(EXAMPLE_LINKEDIN_LAUNCH_PATH.read_text(encoding="utf-8"))
            source = str(EXAMPLE_LINKEDIN_LAUNCH_PATH)
        except (OSError, json.JSONDecodeError):
            raw = None
            source = "defaults"

    merged, notes = deep_merge_defaults(
        raw, LINKEDIN_LAUNCH_DEFAULTS, prefix="linkedin"
    )
    if source == "defaults" or (path is None and not p.exists()):
        notes.insert(
            0,
            "using LinkedIn defaults because config/linkedin.launch.json missing "
            "(see config/linkedin.launch.example.json)",
        )
    try:
        profile = validate_linkedin_dict(merged)
    except Exception as e:
        # Last resort: pure defaults
        notes.append(f"linkedin validation failed ({e}); falling back to pure defaults")
        profile = validate_linkedin_dict(dict(LINKEDIN_LAUNCH_DEFAULTS))
        merged = dict(LINKEDIN_LAUNCH_DEFAULTS)
    used = bool(notes)
    return profile, ConfigLoadResult(
        data=merged, notifications=notes, used_defaults=used, source=source
    )


def save_linkedin_launch(
    profile: LinkedInLaunchProfile, path: Path | None = None
) -> Path:
    p = path or DEFAULT_LINKEDIN_LAUNCH_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(profile.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return p
