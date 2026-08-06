"""Application use-cases."""

from __future__ import annotations

import time
from typing import Any

from app.domain.enums import JobStatus
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.job_runner import JobRunner
from app.infrastructure.settings import Settings


class AppService:
    """Фасад use-cases для API/UI."""

    def __init__(self, uow: UnitOfWork, settings: Settings, runner: JobRunner) -> None:
        self.uow = uow
        self.settings = settings
        self.runner = runner

    # ── LoginSession ──────────────────────────────────────────

    def start_login(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        return self.runner.start_login(profile)

    def confirm_login(self, profile: str = "default") -> dict[str, Any]:
        return self.runner.confirm_login(self._profile(profile))

    # ── StartSearch ───────────────────────────────────────────

    def start_search(self, profile: str = "default") -> dict[str, Any]:
        return self.runner.start_search(self._profile(profile))

    # ── StartApply ────────────────────────────────────────────

    def start_apply(self, profile: str = "default") -> dict[str, Any]:
        return self.runner.start_apply(self._profile(profile))

    # ── StopJob ───────────────────────────────────────────────

    def stop_job(self, profile: str = "default") -> dict[str, Any]:
        return self.runner.stop(self._profile(profile))

    # ── GetStats / status ─────────────────────────────────────

    def get_status(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        st = self.uow.jobs.get_status(profile)
        stats = self.uow.stats(profile)
        sess = self.uow.profiles.get_session_path(profile)
        return {
            "profile": profile,
            "status": st.status.value if isinstance(st.status, JobStatus) else st.status,
            "message": st.message,
            "stats": {**st.stats, **stats},
            "updated_at": st.updated_at,
            "busy": self.runner.is_busy(profile),
            "has_session": bool(sess and __import__("pathlib").Path(sess).exists()),
            "statuses": [s.value for s in JobStatus],
        }

    def get_stats(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        return {
            "profile": profile,
            "stats": self.uow.stats(profile),
            "status": self.get_status(profile),
        }

    def list_vacancies(self, profile: str = "default", limit: int = 100) -> list[dict[str, Any]]:
        profile = self._profile(profile)
        out = []
        for v in self.uow.vacancies.list_for_profile(profile, limit=limit):
            out.append(
                {
                    "id": v.id,
                    "url": v.url,
                    "title": v.title,
                    "category": v.category.value,
                    "score": v.score,
                    "category_reason": v.category_reason,
                    "filter_status": v.filter_status,
                    "apply_status": v.apply_status.value
                    if hasattr(v.apply_status, "value")
                    else v.apply_status,
                    "query": v.query,
                }
            )
        return out

    def recent_logs(self, profile: str = "default", limit: int = 60) -> list[dict[str, Any]]:
        entries = self.uow.journal.recent(self._profile(profile), limit=limit)
        result = []
        for e in entries:
            when = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.ts))
                if e.ts
                else ""
            )
            result.append(
                {
                    "id": e.id,
                    "when": when,
                    "level": e.level,
                    "event": e.event,
                    "message": e.message,
                }
            )
        return result

    def list_profiles(self) -> list[dict[str, Any]]:
        out = []
        for p in self.uow.profiles.list_profiles():
            out.append(
                {
                    "name": p.name,
                    "has_session": p.has_session,
                    "storage_path": p.storage_path,
                }
            )
        return out

    def ensure_profile(self, name: str) -> dict[str, Any]:
        p = self.uow.profiles.ensure_profile(name)
        return {"name": p.name, "ok": True}

    def config_public(self) -> dict[str, Any]:
        s = self.settings
        return {
            "app_name": s.app_name,
            "base_url": s.base_url,
            "search_queries": s.search_list(),
            "apply_limit": s.apply_limit,
            "headless": s.headless,
            "dry_run": s.dry_run,
            "require_remote_or_hybrid": s.require_remote_or_hybrid,
            "skip_gov": s.skip_gov,
            "require_python_keywords": s.require_python_keywords,
            "database_backend": "sqlite" if s.is_sqlite() else "external",
            "max_per_hour": s.max_per_hour,
            "max_per_day": s.max_per_day,
        }

    def _profile(self, profile: str) -> str:
        name = (profile or "default").strip() or "default"
        self.uow.profiles.ensure_profile(name)
        return name
