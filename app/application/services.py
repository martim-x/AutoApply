"""Application use-cases."""

from __future__ import annotations

import time
from typing import Any

from app.application.alerts import get_alert_service
from app.domain.enums import JobStatus
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.job_runner import JobRunner
from app.infrastructure.browser.remote_session import RemoteBrowserManager
from app.infrastructure.browser.workspace import normalize_workspace
from app.infrastructure.settings import Settings


class AppService:
    """Фасад use-cases для API/UI."""

    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        runner: JobRunner,
        remote_browser: RemoteBrowserManager | None = None,
        scheduler: Any | None = None,
        parse_scheduler: Any | None = None,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.runner = runner
        self.remote_browser = remote_browser or RemoteBrowserManager(uow, settings)
        self.scheduler = scheduler
        self.parse_scheduler = parse_scheduler
        self._config_notifications: list[str] = []

    # ── LoginSession ──────────────────────────────────────────

    def start_login(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        # When remote browser is enabled, prefer interactive screencast over local window
        if self.settings.enable_remote_browser:
            if self.runner.is_busy(profile, "hh"):
                return {"ok": False, "error": "hh job already running"}
            return self.remote_browser.start(profile, workspace="hh")
        return self.runner.start_login(profile)

    def confirm_login(
        self, profile: str = "default", *, workspace: str = "hh"
    ) -> dict[str, Any]:
        profile = self._profile(profile)
        ws = normalize_workspace(workspace)
        if self.settings.enable_remote_browser and self.remote_browser.get(
            profile, ws
        ):
            return self.remote_browser.save(profile, workspace=ws)
        return self.runner.confirm_login(profile, service=ws)

    # ── Remote browser (CDP screencast) ────────────────────────

    def start_remote_browser(
        self, profile: str = "default", *, workspace: str = "hh"
    ) -> dict[str, Any]:
        profile = self._profile(profile)
        ws = normalize_workspace(workspace)
        if self.runner.is_busy(profile, ws) and not self.remote_browser.get(
            profile, ws
        ):
            return {"ok": False, "error": f"{ws} job already running"}
        return self.remote_browser.start(profile, workspace=ws)

    def save_remote_browser(
        self, profile: str = "default", *, workspace: str = "hh"
    ) -> dict[str, Any]:
        return self.remote_browser.save(
            self._profile(profile), workspace=normalize_workspace(workspace)
        )

    def stop_remote_browser(
        self,
        profile: str = "default",
        *,
        save: bool = True,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        ws = normalize_workspace(workspace) if workspace is not None else None
        return self.remote_browser.stop(
            self._profile(profile), save=save, workspace=ws
        )

    def remote_browser_status(
        self, profile: str = "default", *, workspace: str = "hh"
    ) -> dict[str, Any]:
        return self.remote_browser.status(
            self._profile(profile), workspace=normalize_workspace(workspace)
        )

    # ── StartSearch ───────────────────────────────────────────

    def start_search(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.remote_browser.get(profile, "hh"):
            return {
                "ok": False,
                "error": "hh remote browser open — закройте или Stop",
            }
        return self.runner.start_search(profile)

    # ── StartApply ────────────────────────────────────────────

    def start_apply(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.remote_browser.get(profile, "hh"):
            return {
                "ok": False,
                "error": "hh remote browser open — закройте или Stop",
            }
        return self.runner.start_apply(profile)

    # ── StopJob ───────────────────────────────────────────────

    def stop_job(
        self, profile: str = "default", *, workspace: str | None = None
    ) -> dict[str, Any]:
        """Stop job and/or remote for one workspace, or all when workspace is None."""
        profile = self._profile(profile)
        ws = normalize_workspace(workspace) if workspace is not None else None
        out: dict[str, Any] = {"ok": True}
        if ws is not None:
            if self.remote_browser.get(profile, ws):
                out["remote"] = self.remote_browser.stop(
                    profile, save=True, workspace=ws
                )
        elif self.remote_browser.any_running(profile):
            out["remote"] = self.remote_browser.stop(
                profile, save=True, workspace=None
            )
        job = self.runner.stop(profile, service=ws)
        remote_msg = (out.get("remote") or {}).get("message") or ""
        job_msg = job.get("message") or ""
        parts = [
            m
            for m in (remote_msg, job_msg)
            if m and m != "nothing to stop"
        ]
        out["message"] = "; ".join(parts) if parts else (job_msg or remote_msg or "stopped")
        if job.get("ok") is False:
            out["ok"] = False
            out["error"] = job.get("error")
        return out

    # ── GetStats / status ─────────────────────────────────────

    def ensure_vacancies_rescored(self) -> int:
        """Re-apply weight map categories when thresholds/version change."""
        import json

        from app.domain.categorize import categorize_vacancy
        from app.domain.launch_profile import load_launch_profile
        from app.domain.scoring.engine import load_weight_map, reload_weight_map

        reload_weight_map()
        wmap = load_weight_map()
        stamp = json.dumps(
            {"v": wmap.get("version"), "t": wmap.get("thresholds")},
            sort_keys=True,
            ensure_ascii=False,
        )
        if self.uow.get_meta("weights_rescore_stamp") == stamp:
            return 0

        launch = load_launch_profile(self.settings.launch_path)
        location = launch.location if launch else None
        updated = 0
        for prof in self.uow.profiles.list_profiles():
            for vac in self.uow.vacancies.list_for_profile(prof.name, limit=50_000):
                cat = categorize_vacancy(
                    vac.title or "",
                    vac.description or "",
                    url=vac.url or "",
                    location=location,
                    launch=launch,
                )
                new_cat = cat.category
                new_score = int(cat.score)
                new_reason = cat.explanation or cat.reason or ""
                old_cat = (
                    vac.category.value
                    if hasattr(vac.category, "value")
                    else str(vac.category)
                )
                if (
                    old_cat == new_cat.value
                    and int(vac.score or 0) == new_score
                    and (vac.category_reason or "") == new_reason
                ):
                    continue
                vac.category = new_cat
                vac.score = new_score
                vac.category_reason = new_reason
                self.uow.vacancies.upsert(vac)
                updated += 1

        self.uow.set_meta("weights_rescore_stamp", stamp)
        if updated:
            self.uow.journal.log(
                "system",
                "vacancies_rescored",
                f"updated={updated} stamp={stamp}",
            )
        return updated

    def get_status(self, profile: str = "default") -> dict[str, Any]:
        from pathlib import Path

        self.ensure_vacancies_rescored()
        profile = self._profile(profile)
        st = self.uow.jobs.get_status(profile)
        stats = self.uow.stats(profile)
        sess = self.uow.profiles.get_session_path(profile)
        hh_path = self.settings.state_path(profile)
        li_path = self.settings.linkedin_state_path(profile)
        has_hh = bool(
            (sess and Path(sess).exists()) or hh_path.exists()
        )
        has_li = li_path.exists()
        alerts = getattr(self.runner, "alerts", None) or get_alert_service(self.settings)
        last_alert = getattr(alerts, "last_alert", None)
        alert_notes = []
        try:
            alert_notes = list(alerts.config_notifications())
        except Exception:
            alert_notes = []
        notifications = list(self._config_notifications) + alert_notes
        if last_alert and last_alert.get("message"):
            notifications = [
                f"alert:{last_alert.get('event', '?')}: {last_alert['message']}"
            ] + notifications
        return {
            "profile": profile,
            "status": st.status.value if isinstance(st.status, JobStatus) else st.status,
            "message": st.message,
            "stats": {**st.stats, **stats},
            "updated_at": st.updated_at,
            "busy": self.runner.is_busy(profile)
            or self.remote_browser.any_running(profile),
            "busy_hh": self.runner.is_busy(profile, "hh")
            or bool(self.remote_browser.get(profile, "hh")),
            "busy_linkedin": self.runner.is_busy(profile, "linkedin")
            or bool(self.remote_browser.get(profile, "linkedin")),
            "has_session": has_hh,
            "has_linkedin_session": has_li,
            "linkedin_stats": {
                **self.uow.linkedin_contacts.stats(profile),
                "vacancies": self.uow.linkedin_vacancies.stats(profile),
            },
            "statuses": [s.value for s in JobStatus],
            "remote_browser": self.remote_browser.status(profile, workspace="hh"),
            "remote_browsers": self.remote_browser.status_all(profile),
            "notifications": notifications,
            "last_alert": last_alert,
            "report_schedule": self.scheduler.status() if self.scheduler else None,
            "parse_schedule": (
                self.parse_scheduler.status() if self.parse_scheduler else None
            ),
        }

    def get_stats(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        return {
            "profile": profile,
            "stats": self.uow.stats(profile),
            "status": self.get_status(profile),
        }

    def list_vacancies(self, profile: str = "default", limit: int = 100) -> list[dict[str, Any]]:
        self.ensure_vacancies_rescored()
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
        from app.domain.launch_profile import load_launch_profile

        launch = load_launch_profile(self.settings.launch_path)
        location = launch.location if launch else None
        data = explain_text(
            vac.title or "",
            vac.description or "",
            url=vac.url or "",
            location=location,
            launch=launch,
        )
        data["ok"] = True
        data["vacancy_id"] = vac.id
        data["title"] = vac.title
        data["url"] = vac.url
        data["stored_category"] = (
            vac.category.value if hasattr(vac.category, "value") else vac.category
        )
        data["stored_score"] = vac.score
        return data

    def recent_logs(
        self,
        profile: str = "default",
        limit: int = 60,
        *,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        from app.domain.entities import normalize_journal_service

        svc = normalize_journal_service(service) if service else None
        entries = self.uow.journal.recent(
            self._profile(profile), limit=limit, service=svc
        )
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
                    "service": e.service,
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

    def rename_profile(self, old_name: str, new_name: str) -> dict[str, Any]:
        old = (old_name or "").strip()
        new = (new_name or "").strip()
        if not old or not new:
            return {"ok": False, "error": "empty profile name"}
        if self.runner.is_busy(old) or self.remote_browser.any_running(old):
            return {"ok": False, "error": "profile busy — stop job / close browser first"}
        try:
            p = self.uow.profiles.rename_profile(old, new)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if old != p.name:
            self._move_session_files(old, p.name)
            new_state = self.settings.state_path(p.name)
            if new_state.exists():
                self.uow.profiles.save_session(p.name, new_state)
        return {"ok": True, "name": p.name, "old_name": old}

    def delete_profile(self, name: str) -> dict[str, Any]:
        profile = (name or "").strip()
        if not profile:
            return {"ok": False, "error": "empty profile name"}
        if self.runner.is_busy(profile) or self.remote_browser.any_running(profile):
            return {"ok": False, "error": "profile busy — stop job / close browser first"}
        try:
            selected = self.uow.profiles.delete_profile(profile)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        self._unlink_session_files(profile)
        return {"ok": True, "deleted": profile, "selected": selected}

    def _move_session_files(self, old_name: str, new_name: str) -> None:
        pairs = (
            (self.settings.state_path(old_name), self.settings.state_path(new_name)),
            (
                self.settings.linkedin_state_path(old_name),
                self.settings.linkedin_state_path(new_name),
            ),
        )
        for src, dst in pairs:
            if not src.exists():
                continue
            if src.resolve() == dst.resolve():
                continue
            if dst.exists():
                src.unlink(missing_ok=True)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)

    def _unlink_session_files(self, profile: str) -> None:
        for path in (
            self.settings.state_path(profile),
            self.settings.linkedin_state_path(profile),
        ):
            path.unlink(missing_ok=True)

    def config_public(self) -> dict[str, Any]:
        from app.domain.launch_profile import (
            load_areas_catalog,
            load_launch_profile_with_notes,
        )
        from app.domain.linkedin_profile import load_linkedin_launch

        s = self.settings
        launch, launch_notes = load_launch_profile_with_notes(s.launch_path)
        li, li_result = load_linkedin_launch(s.linkedin_launch_path)
        notes = list(launch_notes) + list(li_result.notifications)
        sched = s.parse_report_schedule()
        notes.extend(sched.get("notifications") or [])
        parse_sched = s.parse_parse_schedule()
        notes.extend(parse_sched.get("notifications") or [])
        alert_cfg = s.parse_alert_config()
        notes.extend(alert_cfg.get("notifications") or [])
        self._config_notifications = notes
        return {
            "app_name": s.app_name,
            "base_url": launch.base_url if launch else s.base_url,
            "search_queries": list(launch.queries)
            if launch
            else s.search_list(),
            "search_area": launch.search_area if launch else s.search_area,
            "vacancy_limit": launch.vacancy_limit if launch else s.vacancy_limit,
            "apply_limit": launch.apply_limit if launch else s.apply_limit,
            "headless": s.headless,
            "dry_run": launch.dry_run if launch else s.dry_run,
            "require_remote_or_hybrid": (
                launch.require_remote_or_hybrid
                if launch
                else s.require_remote_or_hybrid
            ),
            "skip_gov": launch.skip_gov if launch else s.skip_gov,
            "require_python_keywords": (
                launch.require_python_keywords
                if launch
                else s.require_python_keywords
            ),
            "database_backend": "sqlite" if s.is_sqlite() else "external",
            "max_per_hour": s.max_per_hour,
            "max_per_day": s.max_per_day,
            "enable_remote_browser": s.enable_remote_browser,
            "launch": launch.to_public_dict() if launch else None,
            "linkedin": li.to_public_dict(),
            "sites": list((load_areas_catalog().get("sites") or {}).keys()),
            "workspaces": ["hh", "linkedin"],
            "notifications": notes,
            "report_schedule": (
                self.scheduler.status() if self.scheduler else sched
            ),
            "parse_schedule": (
                self.parse_scheduler.status()
                if self.parse_scheduler
                else parse_sched
            ),
        }

    def get_launch(self) -> dict[str, Any]:
        from app.domain.launch_profile import (
            launch_to_strict_text,
            load_areas_catalog,
            load_launch_profile_with_notes,
        )

        launch, notes = load_launch_profile_with_notes(self.settings.launch_path)
        self._config_notifications = notes
        cat = load_areas_catalog()
        return {
            "ok": True,
            "launch": launch.to_public_dict() if launch else None,
            "strict_text": launch_to_strict_text(launch) if launch else "",
            "example_path": "config/launch.example.json",
            "path": str(self.settings.launch_path),
            "sites": cat.get("sites") or {},
            "locations": [
                {
                    "country": loc["country"],
                    "cities": [c["city"] for c in (loc.get("cities") or [])],
                }
                for loc in (cat.get("locations") or [])
            ],
            "notifications": notes,
        }

    def save_launch_from_text(self, text: str) -> dict[str, Any]:
        from app.domain.launch_profile import (
            launch_to_strict_text,
            parse_and_validate_text,
            save_launch_profile,
        )

        try:
            profile = parse_and_validate_text(text)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        path = save_launch_profile(profile, self.settings.launch_path)
        self.uow.journal.log(
            "system",
            "launch_saved",
            f"{profile.site} / {profile.location.country} / {profile.location.city}",
        )
        return {
            "ok": True,
            "path": str(path),
            "launch": profile.to_public_dict(),
            "strict_text": launch_to_strict_text(profile),
        }

    def save_launch_from_json(self, data: dict[str, Any]) -> dict[str, Any]:
        from app.domain.launch_profile import (
            launch_to_strict_text,
            save_launch_profile,
            validate_launch_dict,
        )

        try:
            profile = validate_launch_dict(data)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        path = save_launch_profile(profile, self.settings.launch_path)
        return {
            "ok": True,
            "path": str(path),
            "launch": profile.to_public_dict(),
            "strict_text": launch_to_strict_text(profile),
        }

    def validate_launch_text(self, text: str) -> dict[str, Any]:
        from app.domain.launch_profile import (
            launch_to_strict_text,
            parse_and_validate_text,
        )

        try:
            profile = parse_and_validate_text(text)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "launch": profile.to_public_dict(),
            "strict_text": launch_to_strict_text(profile),
        }

    # ── LinkedIn workspace ────────────────────────────────────

    def start_linkedin_login(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.settings.enable_remote_browser:
            if self.runner.is_busy(profile, "linkedin"):
                return {"ok": False, "error": "linkedin job already running"}
            return self.remote_browser.start(profile, workspace="linkedin")
        return self.runner.start_linkedin_login(profile)

    def start_linkedin_network(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.remote_browser.get(profile, "linkedin"):
            return {
                "ok": False,
                "error": "linkedin remote browser open — закройте или Stop",
            }
        return self.runner.start_linkedin_network(profile)

    def start_linkedin_vacancies(self, profile: str = "default") -> dict[str, Any]:
        profile = self._profile(profile)
        if self.remote_browser.get(profile, "linkedin"):
            return {
                "ok": False,
                "error": "linkedin remote browser open — закройте или Stop",
            }
        return self.runner.start_linkedin_vacancies(profile)

    def get_linkedin_launch(self) -> dict[str, Any]:
        from app.domain.linkedin_profile import load_linkedin_launch

        lp, result = load_linkedin_launch(self.settings.linkedin_launch_path)
        self._config_notifications = list(result.notifications)
        return {
            "ok": True,
            "launch": lp.to_public_dict(),
            "path": str(self.settings.linkedin_launch_path),
            "example_path": "config/linkedin.launch.example.json",
            "notifications": result.notifications,
            "source": result.source,
        }

    def save_linkedin_launch(self, data: dict[str, Any]) -> dict[str, Any]:
        from app.domain.linkedin_profile import (
            save_linkedin_launch,
            validate_linkedin_dict,
        )

        try:
            profile = validate_linkedin_dict(data)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        path = save_linkedin_launch(profile, self.settings.linkedin_launch_path)
        self.uow.journal.log("system", "linkedin_launch_saved", str(path))
        return {
            "ok": True,
            "path": str(path),
            "launch": profile.to_public_dict(),
        }

    def validate_linkedin_launch(self, data: dict[str, Any]) -> dict[str, Any]:
        from app.domain.linkedin_profile import validate_linkedin_dict

        try:
            profile = validate_linkedin_dict(data)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "launch": profile.to_public_dict(),
        }

    def list_linkedin_contacts(
        self, profile: str = "default", limit: int = 100
    ) -> list[dict[str, Any]]:
        profile = self._profile(profile)
        out = []
        for c in self.uow.linkedin_contacts.list_for_profile(profile, limit=limit):
            out.append(
                {
                    "id": c.id,
                    "url": c.url,
                    "name": c.name,
                    "headline": c.headline,
                    "location": c.location,
                    "query": c.query,
                    "status": c.status,
                    "error": c.error,
                }
            )
        return out

    def list_linkedin_vacancies(
        self, profile: str = "default", limit: int = 100
    ) -> list[dict[str, Any]]:
        profile = self._profile(profile)
        out = []
        for v in self.uow.linkedin_vacancies.list_for_profile(profile, limit=limit):
            out.append(
                {
                    "id": v.id,
                    "url": v.url,
                    "title": v.title,
                    "company": v.company,
                    "location": v.location,
                    "query": v.query,
                    "source": v.source,
                }
            )
        return out

    def list_report_files(self, limit: int = 30) -> list[dict[str, Any]]:
        try:
            return self.uow.report_files.list_recent(limit=limit)
        except Exception:
            return []

    def run_report_now(
        self, *, kind: str = "work", profile: str = "default", scheduled: bool = False
    ) -> dict[str, Any]:
        from app.infrastructure.scheduler import generate_scheduled_report

        return generate_scheduled_report(
            self.uow,
            self.settings,
            kind=kind,
            profile=self._profile(profile),
            scheduled=scheduled,
        )

    def _profile(self, profile: str | None = None) -> str:
        return self.uow.profiles.resolve_profile(profile)
