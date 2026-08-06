"""Repository / gateway ports (swappable implementations)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .entities import Application, JobState, JournalEntry, Profile, Vacancy
from .enums import JobStatus


class ProfileRepository(Protocol):
    def list_profiles(self) -> list[Profile]: ...
    def ensure_profile(self, name: str) -> Profile: ...
    def save_session(self, profile: str, storage_path: Path) -> None: ...
    def get_session_path(self, profile: str) -> str | None: ...


class VacancyRepository(Protocol):
    def upsert(self, vacancy: Vacancy) -> int: ...
    def list_for_profile(
        self,
        profile: str,
        *,
        apply_status: str | None = None,
        limit: int = 200,
    ) -> list[Vacancy]: ...
    def next_queued(self, profile: str, limit: int = 100) -> list[Vacancy]: ...
    def set_apply_status(self, vacancy_pk: int, status: str) -> None: ...


class ApplicationRepository(Protocol):
    def already_applied(self, profile: str, vacancy_url: str) -> bool: ...
    def count_applied_since(self, profile: str, since_ts: float) -> int: ...
    def record(self, application: Application) -> None: ...
    def stats(self, profile: str) -> dict[str, Any]: ...


class JobStateRepository(Protocol):
    def set_status(
        self,
        profile: str,
        status: JobStatus | str,
        message: str = "",
        stats: dict[str, Any] | None = None,
    ) -> None: ...
    def get_status(self, profile: str) -> JobState: ...


class JournalRepository(Protocol):
    def log(
        self,
        profile: str,
        event: str,
        message: str = "",
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None: ...
    def recent(self, profile: str | None = None, limit: int = 80) -> list[JournalEntry]: ...


class UnitOfWork(Protocol):
    """Facade over all repositories — one DB backend."""

    profiles: ProfileRepository
    vacancies: VacancyRepository
    applications: ApplicationRepository
    jobs: JobStateRepository
    journal: JournalRepository

    def stats(self, profile: str) -> dict[str, Any]: ...


class BrowserGateway(Protocol):
    """Playwright (or other) browser automation port."""

    def run_login(self, profile: str, stop_flag: Any) -> None: ...
    def run_search(self, profile: str, stop_flag: Any) -> None: ...
    def run_apply(self, profile: str, stop_flag: Any) -> None: ...
