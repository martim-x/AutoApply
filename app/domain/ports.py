"""Repository / gateway ports (swappable implementations)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .entities import (
    Application,
    JobState,
    JournalEntry,
    LinkedInContact,
    LinkedInVacancyLink,
    Profile,
    Vacancy,
)
from .enums import JobStatus


class ProfileRepository(Protocol):
    def list_profiles(self) -> list[Profile]: ...
    def ensure_profile(self, name: str) -> Profile: ...
    def resolve_profile(self, name: str | None = None) -> str: ...
    def rename_profile(self, old_name: str, new_name: str) -> Profile: ...
    def delete_profile(self, name: str) -> str: ...
    def save_session(self, profile: str, storage_path: Path) -> None: ...
    def get_session_path(self, profile: str) -> str | None: ...


class VacancyRepository(Protocol):
    def upsert(self, vacancy: Vacancy) -> int: ...
    def exists(
        self,
        profile: str,
        *,
        url: str | None = None,
        vacancy_id: str | None = None,
    ) -> bool: ...
    def known_keys(self, profile: str) -> tuple[set[str], set[str]]: ...
    def list_for_profile(
        self,
        profile: str,
        *,
        apply_status: str | None = None,
        limit: int = 200,
        offset: int = 0,
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
        *,
        service: str | None = None,
    ) -> None: ...
    def recent(
        self,
        profile: str | None = None,
        limit: int = 80,
        *,
        service: str | None = None,
        offset: int = 0,
    ) -> list[JournalEntry]: ...


class LinkedInContactRepository(Protocol):
    def upsert(self, contact: LinkedInContact) -> int: ...
    def list_for_profile(
        self, profile: str, limit: int = 200, offset: int = 0
    ) -> list[LinkedInContact]: ...
    def stats(self, profile: str) -> dict[str, Any]: ...


class LinkedInVacancyRepository(Protocol):
    def upsert(self, vacancy: LinkedInVacancyLink) -> int: ...
    def exists(self, profile: str, *, url: str | None = None) -> bool: ...
    def known_urls(self, profile: str) -> set[str]: ...
    def list_for_profile(
        self, profile: str, limit: int = 200, offset: int = 0
    ) -> list[LinkedInVacancyLink]: ...
    def stats(self, profile: str) -> dict[str, Any]: ...


class ReportFileRepository(Protocol):
    def record(
        self,
        profile: str,
        kind: str,
        path: str,
        *,
        scheduled: bool = False,
    ) -> int: ...
    def list_recent(self, limit: int = 30) -> list[dict[str, Any]]: ...
    def last_scheduled(self) -> dict[str, Any] | None: ...


class UnitOfWork(Protocol):
    """Facade over all repositories — one DB backend."""

    profiles: ProfileRepository
    vacancies: VacancyRepository
    applications: ApplicationRepository
    jobs: JobStateRepository
    journal: JournalRepository
    linkedin_contacts: LinkedInContactRepository
    linkedin_vacancies: LinkedInVacancyRepository
    report_files: ReportFileRepository

    def stats(self, profile: str) -> dict[str, Any]: ...

    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...


class BrowserGateway(Protocol):
    """Playwright (or other) browser automation port."""

    def run_login(self, profile: str, stop_flag: Any) -> None: ...
    def run_search(self, profile: str, stop_flag: Any) -> None: ...
    def run_apply(self, profile: str, stop_flag: Any) -> None: ...
