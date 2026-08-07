"""Background thread job runner (stoppable per profile×workspace)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from app.application.alerts import AlertService, get_alert_service
from app.domain.enums import JobStatus
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.gateway import PlaywrightBrowserGateway, safe_run
from app.infrastructure.browser.workspace import browser_slot_key, normalize_workspace
from app.infrastructure.settings import Settings


class StopFlag:
    def __init__(self) -> None:
        self._ev = threading.Event()
        self.save_now = False

    def stop(self) -> None:
        self._ev.set()

    @property
    def stopped(self) -> bool:
        return self._ev.is_set()


class JobRunner:
    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        alerts: AlertService | None = None,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.alerts = alerts or get_alert_service(settings)
        self.gateway = PlaywrightBrowserGateway(uow, settings, alerts=self.alerts)
        from app.infrastructure.browser.linkedin_gateway import LinkedInBrowserGateway

        self.linkedin = LinkedInBrowserGateway(uow, settings, alerts=self.alerts)
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, StopFlag] = {}
        self._services: dict[str, str] = {}

    def is_busy(self, profile: str, service: str | None = None) -> bool:
        """If service is set, only that workspace slot; otherwise any slot for profile."""
        profile = (profile or "default").strip() or "default"
        with self._lock:
            if service is not None:
                t = self._threads.get(browser_slot_key(profile, service))
                return bool(t and t.is_alive())
            prefix = f"{profile}:"
            for key, t in self._threads.items():
                if key.startswith(prefix) and t and t.is_alive():
                    return True
            return False

    def stop(
        self, profile: str, *, service: str | None = None
    ) -> dict[str, Any]:
        """Stop one workspace job, or all jobs for profile when service is None."""
        profile = (profile or "default").strip() or "default"
        stopped: list[str] = []
        with self._lock:
            if service is None:
                keys = [
                    k
                    for k, t in self._threads.items()
                    if k.startswith(f"{profile}:") and t and t.is_alive()
                ]
            else:
                key = browser_slot_key(profile, service)
                t = self._threads.get(key)
                keys = [key] if t and t.is_alive() else []
            for key in keys:
                flag = self._stops.get(key)
                if not flag:
                    continue
                flag.stop()
                svc = self._services.get(key, normalize_workspace(key.rsplit(":", 1)[-1]))
                stopped.append(svc)
                self.uow.journal.log(
                    profile,
                    "stop_requested",
                    "Остановка запрошена",
                    service=svc,
                )
        if stopped:
            # Shared job_state: only nudge when stopping a single known slot
            if len(stopped) == 1:
                self.uow.jobs.set_status(profile, JobStatus.IDLE, "Остановка…")
            return {
                "ok": True,
                "message": "stop requested",
                "workspaces": stopped,
            }
        return {"ok": True, "message": "nothing to stop"}

    def confirm_login(
        self, profile: str, *, service: str = "hh"
    ) -> dict[str, Any]:
        service = normalize_workspace(service)
        key = browser_slot_key(profile, service)
        with self._lock:
            flag = self._stops.get(key)
            if not flag:
                from app.infrastructure.browser.workspace import storage_state_path

                sp = storage_state_path(self.settings, profile, service)
                if sp.exists():
                    if service != "linkedin":
                        self.uow.profiles.save_session(profile, sp)
                    return {"ok": True, "message": "session file already on disk"}
                return {"ok": False, "error": "login job not running"}
            flag.save_now = True
        self.uow.journal.log(
            profile,
            "login_confirm",
            "Пользователь подтвердил вход",
            service=service,
        )
        return {"ok": True, "message": "save requested"}

    def _spawn(
        self,
        profile: str,
        target: Callable[[str, StopFlag], None],
        *,
        service: str = "hh",
    ) -> dict[str, Any]:
        service = normalize_workspace(service)
        key = browser_slot_key(profile, service)
        with self._lock:
            existing = self._threads.get(key)
            if existing and existing.is_alive():
                return {
                    "ok": False,
                    "error": f"{service} job already running",
                }
            self.uow.profiles.ensure_profile(profile)
            stop = StopFlag()
            self._stops[key] = stop
            self._services[key] = service

            def runner() -> None:
                try:
                    safe_run(
                        lambda: target(profile, stop),
                        self.uow,
                        profile,
                        alerts=self.alerts,
                        service=service,
                    )
                finally:
                    with self._lock:
                        self._threads.pop(key, None)
                        self._services.pop(key, None)
                        self._stops.pop(key, None)

            t = threading.Thread(
                target=runner, name=f"job-{profile}-{service}", daemon=True
            )
            self._threads[key] = t
            t.start()
            return {"ok": True, "message": "started", "workspace": service}

    def start_login(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.gateway.run_login, service="hh")

    def start_search(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.gateway.run_search, service="hh")

    def start_apply(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.gateway.run_apply, service="hh")

    def start_linkedin_login(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.linkedin.run_login, service="linkedin")

    def start_linkedin_network(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.linkedin.run_network, service="linkedin")

    def start_linkedin_vacancies(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.linkedin.run_vacancies, service="linkedin")
