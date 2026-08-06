"""Domain enums / value-like constants."""

from __future__ import annotations

from enum import Enum


class FitCategory(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @property
    def priority(self) -> int:
        return {FitCategory.HIGH: 0, FitCategory.MEDIUM: 1, FitCategory.LOW: 2}[self]


class JobStatus(str, Enum):
    IDLE = "idle"
    LOGGING_IN = "logging_in"
    SEARCHING = "searching"
    APPLYING = "applying"
    WAITING_USER = "waiting_user"
    ERROR = "error"
    DONE = "done"


class ApplyStatus(str, Enum):
    QUEUED = "queued"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"
    DRY_RUN = "dry_run"
