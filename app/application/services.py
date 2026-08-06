"""Application use-cases."""

from __future__ import annotations

import time
from typing import Any

from app.domain.enums import JobStatus
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.job_runner import JobRunner
from app.infrastructure.browser.remote_session import RemoteBrowserManager
from app.infrastructure.settings import Settings


class AppService:
    """Фасад use-cases для API/UI."""

    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        runner: JobRunner,
        remote_browser: RemoteBrowserManager | None = None,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.runner = runner
        self.remote_browser = remote_browser or RemoteBrowserManager(uow, settings)

    # ── LoginSession ──────────────────────────────────────────

    def start_login(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        # When remote browser is enabled, prefer interactive screencast over local window
        if self.settings.enable_remote_browser:
            if self.runner.is_busy(profile):
                return {"ok": False, "error": "job already running"}
            return self.remote_browser.start(profile)
        return self.runner.start_login(profile)

    def confirm_login(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.settings.enable_remote_browser and self.remote_browser.get(profile):
            return self.remote_browser.save(profile)
        return self.runner.confirm_login(profile)

    # ── Remote browser (CDP screencast) ────────────────────────

    def start_remote_browser(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.runner.is_busy(profile) and not self.remote_browser.get(profile):
            return {"ok": False, "error": "job already running"}
        return self.remote_browser.start(profile)

    def save_remote_browser(self, profile: str = "default") -> dict[str, Any]:
        return self.remote_browser.save(self._profile(profile))

    def stop_remote_browser(
        self, profile: str = "default", *, save: bool = True
    ) -> dict[str, Any]:
        return self.remote_browser.stop(self._profile(profile), save=save)

    def remote_browser_status(self, profile: str = "default") -> dict[str, Any]:
        return self.remote_browser.status(self._profile(profile))

    # ── StartSearch ───────────────────────────────────────────

    def start_search(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.remote_browser.get(profile):
            return {"ok": False, "error": "remote browser open — закройте или Stop"}
        return self.runner.start_search(profile)

    # ── StartApply ────────────────────────────────────────────

    def start_apply(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.remote_browser.get(profile):
            return {"ok": False, "error": "remote browser open — закройте или Stop"}
        return self.runner.start_apply(profile)

    # ── StopJob ───────────────────────────────────────────────

    def stop_job(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.remote_browser.get(profile):
            return self.remote_browser.stop(profile, save=True)
        return self.runner.stop(profile)

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
            "busy": self.runner.is_busy(profile) or bool(self.remote_browser.get(profile)),
            "has_session": bool(sess and __import__("pathlib").Path(sess).exists()),
            "statuses": [s.value for s in JobStatus],
            "remote_browser": self.remote_browser.status(profile),
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
                    "category": v.category.value
                    if hasattr(v.category, "value")
                    else v.category,
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

    def explain_vacancy(
        self,
        profile: str = "default",
        *,
        vacancy_id: int | None = None,
        url: str | None = None,
    ) -> dict[str, Any]:
        from app.domain.categorize import explain_vacancy as explain_text

        profile = self._profile(profile)
        vac = None
        for v in self.uow.vacancies.list_for_profile(profile, limit=500):
            if vacancy_id is not None and v.id == vacancy_id:
                vac = v
                break
            if url and v.url == url:
                vac = v
                break
        if not vac:
            return {"ok": False, "error": "vacancy not found"}
        data = explain_text(vac.title or "", vac.description or "", url=vac.url or "")
        data["ok"] = True
        data["vacancy_id"] = vac.id
        data["title"] = vac.title
        data["url"] = vac.url
        data["stored_category"] = (
            vac.category.value if hasattr(vac.category, "value") else vac.category
        )
        data["stored_score"] = vac.score
        return data

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
            "enable_remote_browser": s.enable_remote_browser,
        }

    def _profile(self, profile: str) -> str:
        name = (profile or "default").strip() or "default"
        self.uow.profiles.ensure_profile(name)
        return name
