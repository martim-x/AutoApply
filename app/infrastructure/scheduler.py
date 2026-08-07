"""In-process schedulers: PDF reports + vacancy parsing (one uvicorn service)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.reports import assemble_report, normalize_kind
from app.domain.ports import UnitOfWork
from app.infrastructure.reports.pdf import write_report_pdf
from app.infrastructure.settings import Settings

log = logging.getLogger(__name__)


def resolve_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Europe/Minsk")
    except ZoneInfoNotFoundError:
        log.warning("Unknown timezone %r — falling back to Europe/Minsk", name)
        return ZoneInfo("Europe/Minsk")


def next_run_at(hour: int, minute: int, tz: ZoneInfo, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now(tz)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def next_run_at_times(
    times: list[tuple[int, int]],
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
) -> datetime:
    """Soonest future fire among several HH:MM slots in the given timezone."""
    now = now or datetime.now(tz)
    if not times:
        times = [(12, 0), (0, 0)]
    candidates: list[datetime] = []
    for hour, minute in times:
        candidate = now.replace(
            hour=int(hour), minute=int(minute), second=0, microsecond=0
        )
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        candidates.append(candidate)
    return min(candidates)


def generate_scheduled_report(
    uow: UnitOfWork,
    settings: Settings,
    *,
    kind: str | None = None,
    profile: str | None = None,
    scheduled: bool = True,
) -> dict[str, Any]:
    """Write PDF under data/reports/ and journal + report_files row."""
    sched = settings.parse_report_schedule()
    kind = normalize_kind(kind or sched["kind"])
    profile = (profile or sched["profile"] or "default").strip() or "default"
    settings.ensure_dirs()
    payload = assemble_report(uow, settings, kind, profile)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    out = settings.reports_dir / f"auto-apply-app-{kind}-{profile}-{stamp}.pdf"
    write_report_pdf(payload, out)
    uow.report_files.record(profile, kind, str(out), scheduled=scheduled)
    label = "scheduled" if scheduled else "manual"
    uow.journal.log(
        profile,
        "report_generated",
        f"{label} PDF {kind} → {out.name}",
        payload={"path": str(out), "kind": kind, "scheduled": scheduled},
    )
    return {
        "ok": True,
        "path": str(out),
        "kind": kind,
        "profile": profile,
        "scheduled": scheduled,
        "created_at": time.time(),
    }


class ReportScheduler:
    """Async loop sleeping until next local fire time."""

    def __init__(self, uow: UnitOfWork, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_run_at: float | None = None
        self.last_error: str | None = None
        self.next_run_iso: str | None = None

    def status(self) -> dict[str, Any]:
        sched = self.settings.parse_report_schedule()
        last = None
        try:
            last = self.uow.report_files.last_scheduled()
        except Exception:
            last = None
        return {
            **sched,
            "running": bool(self._task and not self._task.done()),
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "next_run_iso": self.next_run_iso,
            "last_file": last,
        }

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="report-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            sched = self.settings.parse_report_schedule()
            if not sched["enabled"]:
                self.next_run_iso = None
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=60.0)
                except TimeoutError:
                    continue
                break

            tz = resolve_tz(sched["timezone"])
            nxt = next_run_at(sched["hour"], sched["minute"], tz)
            self.next_run_iso = nxt.isoformat()
            delay = max(1.0, (nxt - datetime.now(tz)).total_seconds())
            log.info("Report scheduler: next run at %s (sleep %.0fs)", self.next_run_iso, delay)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                break
            except TimeoutError:
                pass

            if self._stop.is_set():
                break
            try:
                result = await asyncio.to_thread(
                    generate_scheduled_report,
                    self.uow,
                    self.settings,
                    kind=sched["kind"],
                    profile=sched["profile"],
                    scheduled=True,
                )
                self.last_run_at = time.time()
                self.last_error = None
                log.info("Scheduled report written: %s", result.get("path"))
            except Exception as e:
                self.last_error = str(e)
                log.exception("Scheduled report failed: %s", e)
                self.uow.journal.log(
                    sched["profile"],
                    "report_schedule_error",
                    str(e),
                    level="error",
                )
                # avoid tight retry loop
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=120.0)
                except TimeoutError:
                    pass


class ParseScheduler:
    """
    Async loop for vacancy parsing at PARSE_SCHEDULE_TIMES (e.g. 12:00 + 00:00).

    Runs HH search and/or LinkedIn vacancy collect when sessions exist
    (prefer both). Same in-process constraint as ReportScheduler.
    """

    def __init__(self, uow: UnitOfWork, settings: Settings, runner: Any) -> None:
        self.uow = uow
        self.settings = settings
        self.runner = runner
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_run_at: float | None = None
        self.last_error: str | None = None
        self.next_run_iso: str | None = None
        self.last_result: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        sched = self.settings.parse_parse_schedule()
        return {
            **sched,
            "running": bool(self._task and not self._task.done()),
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "next_run_iso": self.next_run_iso,
            "last_result": self.last_result,
        }

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="parse-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            sched = self.settings.parse_parse_schedule()
            if not sched["enabled"]:
                self.next_run_iso = None
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=60.0)
                except TimeoutError:
                    continue
                break

            tz = resolve_tz(sched["timezone"])
            nxt = next_run_at_times(list(sched["times"]), tz)
            self.next_run_iso = nxt.isoformat()
            delay = max(1.0, (nxt - datetime.now(tz)).total_seconds())
            log.info(
                "Parse scheduler: next run at %s (sleep %.0fs)",
                self.next_run_iso,
                delay,
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                break
            except TimeoutError:
                pass

            if self._stop.is_set():
                break
            try:
                result = await self._fire(sched)
                self.last_run_at = time.time()
                self.last_error = None
                self.last_result = result
                log.info("Scheduled parse done: %s", result)
            except Exception as e:
                self.last_error = str(e)
                log.exception("Scheduled parse failed: %s", e)
                self.uow.journal.log(
                    sched["profile"],
                    "parse_schedule_error",
                    str(e),
                    level="error",
                )
                try:
                    from app.application.alerts import get_alert_service

                    get_alert_service(self.settings).notify_error(
                        sched["profile"],
                        str(e),
                        event="parse_schedule_error",
                    )
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=120.0)
                except TimeoutError:
                    pass

    async def _wait_idle(self, profile: str, *, timeout: float = 3600.0) -> bool:
        """Wait until JobRunner is free for profile. Returns False on stop/timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._stop.is_set():
                return False
            if not self.runner.is_busy(profile):
                return True
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                return False
            except TimeoutError:
                continue
        return False

    async def _fire(self, sched: dict[str, Any]) -> dict[str, Any]:
        profile = self.uow.profiles.resolve_profile(sched.get("profile"))
        hh_path = self.settings.state_path(profile)
        li_path = self.settings.linkedin_state_path(profile)
        has_hh = hh_path.exists()
        has_li = li_path.exists()

        self.uow.journal.log(
            profile,
            "parse_scheduled",
            f"start hh={has_hh} linkedin={has_li} times={sched.get('times_display')}",
            payload={
                "hh": has_hh,
                "linkedin": has_li,
                "timezone": sched.get("timezone"),
            },
        )

        started: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        if not has_hh and not has_li:
            msg = "no browser sessions — skip scheduled parse"
            self.uow.journal.log(profile, "parse_scheduled_skip", msg, level="warning")
            return {"ok": False, "error": msg, "started": [], "skipped": ["hh", "linkedin"]}

        if not await self._wait_idle(profile, timeout=600.0):
            msg = "profile busy — deferred parse aborted"
            self.uow.journal.log(profile, "parse_scheduled_busy", msg, level="warning")
            return {"ok": False, "error": msg, "started": started, "skipped": skipped}

        if has_hh:
            res = self.runner.start_search(profile)
            if res.get("ok"):
                started.append("hh")
                await self._wait_idle(profile)
            else:
                errors.append(f"hh:{res.get('error')}")
                skipped.append("hh")
        else:
            skipped.append("hh")

        if self._stop.is_set():
            return {"ok": False, "started": started, "skipped": skipped, "errors": errors}

        if has_li:
            if not await self._wait_idle(profile, timeout=600.0):
                errors.append("linkedin:busy")
            else:
                res = self.runner.start_linkedin_vacancies(profile)
                if res.get("ok"):
                    started.append("linkedin")
                    await self._wait_idle(profile)
                else:
                    errors.append(f"linkedin:{res.get('error')}")
                    skipped.append("linkedin")
        else:
            skipped.append("linkedin")

        self.uow.journal.log(
            profile,
            "parse_scheduled_done",
            f"started={started} skipped={skipped} errors={errors}",
            payload={"started": started, "skipped": skipped, "errors": errors},
        )
        return {
            "ok": not errors,
            "started": started,
            "skipped": skipped,
            "errors": errors,
        }
