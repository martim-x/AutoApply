"""Конфигурация из .env / окружения (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """
    Секреты и настройки — только из env / .env.
    Env-имена = UPPER_SNAKE поля (DATABASE_URL, DATA_DIR, …).

    DATABASE_URL:
      - sqlite:///./data/rabota_apply.sqlite  (default)
      - postgresql+psycopg://user:pass@host:5432/rabota_apply  (future)
    """

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "RABOTA_APPLY"
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # DB — sqlite by default; postgres-style URL ready for later adapter
    database_url: str = Field(
        default=f"sqlite:///{ROOT / 'data' / 'rabota_apply.sqlite'}",
    )
    data_dir: Path = Field(default=ROOT / "data")
    sessions_dir: Path | None = Field(default=None)
    letter_path: Path = Field(default=ROOT / "letter_universal.txt")

    # Site / search
    base_url: str = "https://rabota.by"
    search_area: str = "16"  # BY
    search_queries: str = (
        "python-разработчик,python-developer,python разработчик,python developer"
    )
    apply_limit: int = 30
    dry_run: bool = False
    headless: bool = False

    # Filters
    require_remote_or_hybrid: bool = True
    skip_gov: bool = True
    require_python_keywords: bool = True

    # Rate limits / retry
    min_action_interval: float = 2.0
    after_apply_delay: float = 8.0
    jitter: float = 0.35
    max_per_hour: int = 40
    max_per_day: int = 180
    load_retries: int = 3
    load_retry_delay: float = 2.5
    apply_retries: int = 2
    navigation_timeout_ms: int = 45_000
    content_timeout_ms: int = 20_000
    settle_ms: int = 1200

    # Optional future secrets
    api_key: str | None = None
    db_password: str | None = None

    @field_validator("data_dir", "letter_path", mode="before")
    @classmethod
    def _as_path(cls, v: Any) -> Path:
        return Path(v) if not isinstance(v, Path) else v

    @property
    def resolved_sessions_dir(self) -> Path:
        return self.sessions_dir or (self.data_dir / "sessions")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_sessions_dir.mkdir(parents=True, exist_ok=True)

    def sqlite_path(self) -> Path | None:
        url = self.database_url
        if url.startswith("sqlite:///"):
            raw = url.removeprefix("sqlite:///")
            p = Path(raw)
            if not p.is_absolute():
                p = ROOT / p
            return p
        return None

    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite:")

    def search_list(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for part in self.search_queries.replace("\n", ",").split(","):
            q = part.strip()
            if not q:
                continue
            key = q.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(q)
        return out or ["python разработчик"]

    def state_path(self, profile: str) -> Path:
        self.ensure_dirs()
        return self.resolved_sessions_dir / f"{profile}.storage.json"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
