"""Domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import ApplyStatus, FitCategory, JobStatus


@dataclass
class Profile:
    name: str
    storage_path: str | None = None
    storage_saved_at: float | None = None
    notes: str | None = None
    created_at: float | None = None

    @property
    def has_session(self) -> bool:
        if not self.storage_path:
            return False
        from pathlib import Path

        return Path(self.storage_path).exists()


@dataclass
class Vacancy:
    url: str
    profile: str
    id: int | None = None
    vacancy_id: str | None = None
    title: str = ""
    description: str = ""
    query: str = ""
    serp_url: str = ""
    category: FitCategory = FitCategory.LOW
    score: int = 0
    category_reason: str = ""
    filter_status: str = "pending"
    apply_status: ApplyStatus = ApplyStatus.QUEUED
    created_at: float | None = None
    updated_at: float | None = None


@dataclass
class Application:
    profile: str
    vacancy_url: str
    status: str
    id: int | None = None
    vacancy_id: str | None = None
    title: str = ""
    category: str | None = None
    attempt: int = 1
    error: str | None = None
    dry_run: bool = False
    duration_ms: int | None = None
    created_at: float | None = None


@dataclass
class JobState:
    profile: str
    status: JobStatus = JobStatus.IDLE
    message: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    updated_at: float | None = None


@dataclass(frozen=True)
class FilterResult:
    ok: bool
    reason: str

    @property
    def status(self) -> str:
        return self.reason


@dataclass(frozen=True)
class CategoryResult:
    category: FitCategory
    score: int
    reason: str
    explanation: str = ""
    contributions: tuple = ()
    total_weight: float = 0.0


JOURNAL_SERVICES = frozenset({"hh", "linkedin"})


def normalize_journal_service(
    service: str | None = None, *, event: str = ""
) -> str:
    """Map to hh|linkedin; infer linkedin from event name when omitted."""
    if service in JOURNAL_SERVICES:
        return service  # type: ignore[return-value]
    ev = (event or "").lower()
    if ev.startswith("linkedin_"):
        return "linkedin"
    return "hh"


@dataclass
class JournalEntry:
    profile: str
    event: str
    message: str = ""
    level: str = "info"
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float | None = None
    id: int | None = None
    service: str = "hh"


@dataclass
class LinkedInContact:
    profile: str
    url: str
    id: int | None = None
    name: str = ""
    headline: str = ""
    location: str = ""
    query: str = ""
    status: str = "pending"  # connected | pending | skipped | error | dry_run
    error: str | None = None
    created_at: float | None = None
    updated_at: float | None = None


@dataclass
class LinkedInVacancyLink:
    profile: str
    url: str
    id: int | None = None
    title: str = ""
    company: str = ""
    location: str = ""
    query: str = ""
    source: str = "linkedin"
    created_at: float | None = None
    updated_at: float | None = None
