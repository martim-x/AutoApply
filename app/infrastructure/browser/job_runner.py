"""Background thread job runner (stoppable per profile)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from app.application.alerts import AlertService, get_alert_service
from app.domain.enums import JobStatus
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.gateway import PlaywrightBrowserGateway, safe_run
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

    def is_busy(self, profile: str) -> bool:
        t = self._threads.get(profile)
        return bool(t and t.is_alive())

    def stop(self, profile: str) -> dict[str, Any]:
        flag = self._stops.get(profile)
        if flag:
            flag.stop()
            self.uow.journal.log(profile, "stop_requested", "Остановка запрошена")
            self.uow.jobs.set_status(profile, JobStatus.IDLE, "Остановка…")
            return {"ok": True, "message": "stop requested"}
        return {"ok": True, "message": "nothing to stop"}

    def confirm_login(self, profile: str) -> dict[str, Any]:
        with self._lock:
            flag = self._stops.get(profile)
            if not flag:
                # save session path may already exist from previous login
                sp = self.settings.state_path(profile)
                if sp.exists():
                    self.uow.profiles.save_session(profile, sp)
                    return {"ok": True, "message": "session file already on disk"}
                return {"ok": False, "error": "login job not running"}
            flag.save_now = True
        self.uow.journal.log(profile, "login_confirm", "Пользователь подтвердил вход")
        return {"ok": True, "message": "save requested"}

    def _spawn(self, profile: str, target: Callable[[str, StopFlag], None]) -> dict[str, Any]:
        with self._lock:
            if self.is_busy(profile):
                return {"ok": False, "error": "job already running"}
            self.uow.profiles.ensure_profile(profile)
            stop = StopFlag()
            self._stops[profile] = stop

            def runner() -> None:
                try:
                    safe_run(
                        lambda: target(profile, stop),
                        self.uow,
                        profile,
                        alerts=self.alerts,
                    )
                finally:
                    with self._lock:
                        self._threads.pop(profile, None)

            t = threading.Thread(target=runner, name=f"job-{profile}", daemon=True)
            self._threads[profile] = t
            t.start()
            return {"ok": True, "message": "started"}

    def start_login(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.gateway.run_login)

    def start_search(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.gateway.run_search)

    def start_apply(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.gateway.run_apply)

    def start_linkedin_login(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.linkedin.run_login)

    def start_linkedin_network(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.linkedin.run_network)

    def start_linkedin_vacancies(self, profile: str) -> dict[str, Any]:
        return self._spawn(profile, self.linkedin.run_vacancies)
