"""In-process schedulers: PDF reports + vacancy parsing (one uvicorn service)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.application.reports import assemble_report, normalize_kind
from app.domain.ports import UnitOfWork
from app.infrastructure.reports.pdf import write_report_pdf
from app.infrastructure.settings import Settings
from app.infrastructure.timefmt import resolve_tz, stamp_now

log = logging.getLogger(__name__)

# Re-read launch.json / env schedule at least this often so UI edits apply
# without process restart (sleep is min(POLL, seconds_until_next)).
SCHEDULE_POLL_SECONDS = 30.0

# Re-export for callers/tests that import resolve_tz from scheduler.
__all__ = [
    "resolve_tz",
    "next_run_at",
    "next_run_at_times",
    "generate_scheduled_report",
    "ReportScheduler",
    "ParseScheduler",
    "resolve_effective_parse_schedule",
    "cron_bit",
    "SCHEDULE_POLL_SECONDS",
]


async def _sleep_until_wake(
    stop: asyncio.Event,
    wake: asyncio.Event,
    timeout: float,
) -> bool:
    """
    Sleep up to timeout, or until stop/wake. Returns True if stop was set.
    """
    wake.clear()
    if stop.is_set():
        return True
    stop_task = asyncio.create_task(stop.wait())
    wake_task = asyncio.create_task(wake.wait())
    try:
        done, pending = await asyncio.wait(
            {stop_task, wake_task},
            timeout=max(0.05, timeout),
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        if not stop_task.done():
            stop_task.cancel()
        if not wake_task.done():
            wake_task.cancel()
    return stop.is_set()


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


# cron_job_rules indices (left→right)
BIT_HH_SEARCH = 0
BIT_HH_APPLY = 1
BIT_LI_VACANCIES = 2
BIT_LI_NETWORK = 3


def cron_bit(rules: str | None, index: int) -> bool:
    bits = (rules or "0000") + "0000"
    return bits[index] == "1"


def resolve_effective_parse_schedule(settings: Settings) -> dict[str, Any]:
    """
    Merge launch.schedule with env PARSE_SCHEDULE_*.

    - Env PARSE_SCHEDULE_ENABLED is a kill-switch (must be true to run).
    - Profile schedule supplies times / timezone / bitmask / email flag.
    - Env times/timezone used as fallback when profile schedule is absent.
    - SERP knobs and profile name stay env-driven.
    """
    from app.domain.launch_profile import load_launch_profile
    from app.infrastructure.settings import parse_schedule_times_list

    env = settings.parse_parse_schedule()
    notes = list(env.get("notifications") or [])
    launch = load_launch_profile(settings.launch_path)
    sched = launch.schedule if launch else None

    if sched is None:
        rules = "1010"  # legacy: HH search + LI vacancies
        return {
            **env,
            "cron_job_rules": rules,
            "email_report_after_run": True,
            "hh_search": cron_bit(rules, BIT_HH_SEARCH),
            "hh_apply": cron_bit(rules, BIT_HH_APPLY),
            "li_vacancies": cron_bit(rules, BIT_LI_VACANCIES),
            "li_network": cron_bit(rules, BIT_LI_NETWORK),
            "source": "env",
            "notifications": notes,
        }

    # Kill-switch: env must allow the scheduler process.
    enabled = bool(settings.parse_schedule_enabled) and bool(sched.enabled)
    if not settings.parse_schedule_enabled:
        notes.append(
            "PARSE_SCHEDULE_ENABLED=false — kill-switch; profile schedule ignored for firing"
        )
    elif not sched.enabled:
        notes.append("launch.schedule.enabled=false — scheduled parse idle")

    times_raw = ",".join(sched.times) if sched.times else settings.parse_schedule_times
    times, time_notes = parse_schedule_times_list(times_raw)
    notes.extend(time_notes)
    tz = (sched.timezone or env.get("timezone") or "Europe/Minsk").strip()
    rules = sched.cron_job_rules or "1111"

    return {
        "enabled": enabled,
        "timezone": tz,
        "times": times,
        "times_display": ",".join(f"{h:02d}:{m:02d}" for h, m in times),
        "profile": env["profile"],
        "early_stop_enabled": env["early_stop_enabled"],
        "old_streak_stop": env["old_streak_stop"],
        "max_serp_pages": env["max_serp_pages"],
        "dup_page_stop": env["dup_page_stop"],
        "cron_job_rules": rules,
        "email_report_after_run": bool(sched.email_report_after_run),
        "hh_search": cron_bit(rules, BIT_HH_SEARCH),
        "hh_apply": cron_bit(rules, BIT_HH_APPLY),
        "li_vacancies": cron_bit(rules, BIT_LI_VACANCIES),
        "li_network": cron_bit(rules, BIT_LI_NETWORK),
        "workspaces": [
            name
            for name, on in (
                ("hh", cron_bit(rules, BIT_HH_SEARCH) or cron_bit(rules, BIT_HH_APPLY)),
                (
                    "linkedin",
                    cron_bit(rules, BIT_LI_VACANCIES) or cron_bit(rules, BIT_LI_NETWORK),
                ),
            )
            if on
        ],
        "source": "launch+env",
        "notifications": notes,
    }


def _maybe_email_report(
    uow: UnitOfWork,
    settings: Settings,
    *,
    payload: Any,
    pdf_path: Any,
    profile: str,
    kind: str,
    scheduled: bool,
) -> bool:
    """
    Send HTML report + PDF via ALERT_SMTP_*.
    Failures are logged + journaled; never raise (scheduler must stay alive).
    """
    try:
        from app.infrastructure.alerts.smtp import send_report_email
        from app.infrastructure.email_templates import render_report_email

        plain, html_body = render_report_email(payload, pdf_name=pdf_path.name)
        subject = f"[auto-apply-app] {payload.title} · {profile}"
        result = send_report_email(
            settings,
            subject=subject,
            body=plain,
            html_body=html_body,
            pdf_path=pdf_path,
        )
        if isinstance(result, tuple):
            ok, detail = bool(result[0]), str(result[1] if len(result) > 1 else "")
        else:
            ok, detail = bool(result), ""
        if ok:
            uow.journal.log(
                profile,
                "report_emailed",
                f"PDF {kind} → mail ({pdf_path.name})",
                payload={
                    "path": str(pdf_path),
                    "kind": kind,
                    "scheduled": scheduled,
                },
            )
            log.info("Report emailed: %s", pdf_path.name)
            return True
        # Distinguish config skip vs real SMTP failure (Yandex auth, etc.).
        event = (
            "report_email_skipped"
            if detail.startswith("ALERT_SMTP_")
            else "report_email_error"
        )
        uow.journal.log(
            profile,
            event,
            f"{detail or 'SMTP failed'} — PDF kept on disk",
            payload={
                "path": str(pdf_path),
                "kind": kind,
                "scheduled": scheduled,
                "detail": detail,
            },
            level="warning",
        )
        return False
    except Exception as e:
        log.warning("Report email failed (PDF kept): %s", e)
        try:
            uow.journal.log(
                profile,
                "report_email_error",
                str(e),
                payload={"path": str(pdf_path), "kind": kind},
                level="error",
            )
        except Exception:
            pass
        return False


def generate_scheduled_report(
    uow: UnitOfWork,
    settings: Settings,
    *,
    kind: str | None = None,
    profile: str | None = None,
    scheduled: bool = True,
    email: bool | None = None,
) -> dict[str, Any]:
    """
    Write PDF under data/reports/ and journal + report_files row.
    When email is True (default for scheduled), also send HTML + PDF via ALERT_SMTP_*.
    """
    sched = settings.parse_report_schedule()
    kind = normalize_kind(kind or sched["kind"])
    profile = (profile or sched["profile"] or "default").strip() or "default"
    send_mail = scheduled if email is None else bool(email)
    settings.ensure_dirs()
    payload = assemble_report(uow, settings, kind, profile)
    stamp = stamp_now(settings=settings)
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
    emailed = False
    if send_mail:
        emailed = _maybe_email_report(
            uow,
            settings,
            payload=payload,
            pdf_path=out,
            profile=profile,
            kind=kind,
            scheduled=scheduled,
        )
    return {
        "ok": True,
        "path": str(out),
        "kind": kind,
        "profile": profile,
        "scheduled": scheduled,
        "emailed": emailed,
        "created_at": time.time(),
    }


class ReportScheduler:
    """Async loop: poll schedule often, fire at next local time."""

    def __init__(self, uow: UnitOfWork, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self.last_run_at: float | None = None
        self.last_error: str | None = None
        self.next_run_iso: str | None = None

    def nudge(self) -> None:
        """Wake the sleep loop so schedule changes apply immediately."""
        self._wake.set()

    def status(self) -> dict[str, Any]:
        sched = self.settings.parse_report_schedule()
        last = None
        try:
            last = self.uow.report_files.last_scheduled()
        except Exception:
            last = None
        next_iso = None
        if sched.get("enabled"):
            tz = resolve_tz(sched["timezone"])
            next_iso = next_run_at(sched["hour"], sched["minute"], tz).isoformat()
            self.next_run_iso = next_iso
        else:
            self.next_run_iso = None
        return {
            **sched,
            "running": bool(self._task and not self._task.done()),
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "next_run_iso": next_iso,
            "last_file": last,
        }

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._wake.clear()
        self._task = asyncio.create_task(self._loop(), name="report-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        target: datetime | None = None
        target_key: tuple[Any, ...] | None = None
        while not self._stop.is_set():
            sched = self.settings.parse_report_schedule()
            if not sched["enabled"]:
                self.next_run_iso = None
                target = None
                target_key = None
                if await _sleep_until_wake(self._stop, self._wake, 60.0):
                    break
                continue

            tz = resolve_tz(sched["timezone"])
            key = (
                int(sched["hour"]),
                int(sched["minute"]),
                sched["timezone"],
                sched.get("kind"),
                sched.get("profile"),
            )
            now = datetime.now(tz)
            nxt = next_run_at(sched["hour"], sched["minute"], tz, now=now)
            if target is None or key != target_key:
                if target is not None and key != target_key:
                    log.info(
                        "Report schedule changed: next_run %s → %s",
                        target.isoformat(),
                        nxt.isoformat(),
                    )
                target = nxt
                target_key = key
                log.info(
                    "Report scheduler: next run at %s",
                    target.isoformat(),
                )

            self.next_run_iso = target.isoformat()
            delay = (target - datetime.now(tz)).total_seconds()
            if delay <= 0:
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
                    if await _sleep_until_wake(self._stop, self._wake, 120.0):
                        break
                target = None
                target_key = None
                continue

            chunk = min(SCHEDULE_POLL_SECONDS, max(0.5, delay))
            if await _sleep_until_wake(self._stop, self._wake, chunk):
                break


class ParseScheduler:
    """
    Async loop for vacancy jobs at launch.schedule times (env kill-switch).

    Bitmask cron_job_rules: HH search, HH apply, LI vacancies, LI network.
    Re-reads launch.json every ≤ SCHEDULE_POLL_SECONDS so Criteria edits
    reschedule without process restart.
    """

    def __init__(self, uow: UnitOfWork, settings: Settings, runner: Any) -> None:
        self.uow = uow
        self.settings = settings
        self.runner = runner
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self.last_run_at: float | None = None
        self.last_error: str | None = None
        self.next_run_iso: str | None = None
        self.last_result: dict[str, Any] | None = None

    def nudge(self) -> None:
        """Wake the sleep loop so launch.schedule edits apply immediately."""
        self._wake.set()

    def status(self) -> dict[str, Any]:
        sched = resolve_effective_parse_schedule(self.settings)
        next_iso = None
        if sched.get("enabled"):
            tz = resolve_tz(sched["timezone"])
            next_iso = next_run_at_times(list(sched["times"]), tz).isoformat()
            self.next_run_iso = next_iso
        else:
            self.next_run_iso = None
        return {
            **sched,
            "running": bool(self._task and not self._task.done()),
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "next_run_iso": next_iso,
            "last_result": self.last_result,
        }

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._wake.clear()
        self._task = asyncio.create_task(self._loop(), name="parse-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        target: datetime | None = None
        target_key: tuple[Any, ...] | None = None
        while not self._stop.is_set():
            # Env kill-switch: process was started with flag off → idle until stop.
            if not self.settings.parse_schedule_enabled:
                self.next_run_iso = None
                target = None
                target_key = None
                if await _sleep_until_wake(self._stop, self._wake, 60.0):
                    break
                continue

            sched = resolve_effective_parse_schedule(self.settings)
            if not sched["enabled"]:
                self.next_run_iso = None
                target = None
                target_key = None
                if await _sleep_until_wake(
                    self._stop, self._wake, SCHEDULE_POLL_SECONDS
                ):
                    break
                continue

            tz = resolve_tz(sched["timezone"])
            times = list(sched["times"])
            key = (
                tuple(times),
                sched["timezone"],
                sched.get("cron_job_rules"),
                bool(sched.get("email_report_after_run")),
            )
            now = datetime.now(tz)
            nxt = next_run_at_times(times, tz, now=now)
            if target is None or key != target_key:
                if target is not None and key != target_key:
                    log.info(
                        "Parse schedule changed: next_run %s → %s rules=%s",
                        target.isoformat(),
                        nxt.isoformat(),
                        sched.get("cron_job_rules"),
                    )
                target = nxt
                target_key = key
                log.info(
                    "Parse scheduler: next run at %s rules=%s",
                    target.isoformat(),
                    sched.get("cron_job_rules"),
                )

            self.next_run_iso = target.isoformat()
            delay = (target - datetime.now(tz)).total_seconds()
            if delay <= 0:
                # Re-resolve so UI-saved launch.schedule applies at fire time.
                sched = resolve_effective_parse_schedule(self.settings)
                if not sched["enabled"]:
                    target = None
                    target_key = None
                    continue
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
                    if await _sleep_until_wake(self._stop, self._wake, 120.0):
                        break
                target = None
                target_key = None
                continue

            chunk = min(SCHEDULE_POLL_SECONDS, max(0.5, delay))
            if await _sleep_until_wake(self._stop, self._wake, chunk):
                break

    async def _wait_idle(
        self,
        profile: str,
        *,
        service: str | None = None,
        timeout: float = 3600.0,
    ) -> bool:
        """Wait until JobRunner slot is free. Returns False on stop/timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._stop.is_set():
                return False
            if not self.runner.is_busy(profile, service):
                return True
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                return False
            except TimeoutError:
                continue
        return False

    async def _start_job(
        self,
        *,
        profile: str,
        service: str,
        label: str,
        start_fn: Any,
        started: list[str],
        skipped: list[str],
        errors: list[str],
        wait_services: list[str],
    ) -> None:
        if self.runner.is_busy(profile, service):
            errors.append(f"{label}:busy")
            skipped.append(label)
            return
        res = start_fn(profile)
        if res.get("ok"):
            started.append(label)
            if service not in wait_services:
                wait_services.append(service)
        else:
            errors.append(f"{label}:{res.get('error')}")
            skipped.append(label)

    async def _fire(self, sched: dict[str, Any]) -> dict[str, Any]:
        profile = self.uow.profiles.resolve_profile(sched.get("profile"))
        hh_path = self.settings.state_path(profile)
        li_path = self.settings.linkedin_state_path(profile)
        has_hh = hh_path.exists()
        has_li = li_path.exists()
        want_hh_search = bool(sched.get("hh_search"))
        want_hh_apply = bool(sched.get("hh_apply"))
        want_li_vac = bool(sched.get("li_vacancies"))
        want_li_net = bool(sched.get("li_network"))

        self.uow.journal.log(
            profile,
            "parse_scheduled",
            (
                f"start rules={sched.get('cron_job_rules')} "
                f"hh={has_hh} linkedin={has_li} times={sched.get('times_display')}"
            ),
            payload={
                "hh": has_hh,
                "linkedin": has_li,
                "timezone": sched.get("timezone"),
                "cron_job_rules": sched.get("cron_job_rules"),
            },
        )

        started: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []
        emailed = False

        need_hh = (want_hh_search or want_hh_apply) and has_hh
        need_li = (want_li_vac or want_li_net) and has_li
        if not need_hh and not need_li:
            msg = "no sessions or no jobs enabled in cron_job_rules — skip"
            self.uow.journal.log(profile, "parse_scheduled_skip", msg, level="warning")
            return {
                "ok": False,
                "error": msg,
                "started": [],
                "skipped": ["hh_search", "hh_apply", "li_vacancies", "li_network"],
                "emailed": False,
            }

        if not await self._wait_idle(profile, timeout=600.0):
            msg = "profile busy — deferred parse aborted"
            self.uow.journal.log(profile, "parse_scheduled_busy", msg, level="warning")
            return {
                "ok": False,
                "error": msg,
                "started": started,
                "skipped": skipped,
                "emailed": False,
            }

        # Wave 1: HH search + LI vacancies (parallel workspaces).
        wait_services: list[str] = []
        if want_hh_search and has_hh:
            await self._start_job(
                profile=profile,
                service="hh",
                label="hh_search",
                start_fn=self.runner.start_search,
                started=started,
                skipped=skipped,
                errors=errors,
                wait_services=wait_services,
            )
        elif want_hh_search:
            skipped.append("hh_search")
        else:
            skipped.append("hh_search")

        if want_li_vac and has_li:
            await self._start_job(
                profile=profile,
                service="linkedin",
                label="li_vacancies",
                start_fn=self.runner.start_linkedin_vacancies,
                started=started,
                skipped=skipped,
                errors=errors,
                wait_services=wait_services,
            )
        elif want_li_vac:
            skipped.append("li_vacancies")
        else:
            skipped.append("li_vacancies")

        for svc in list(wait_services):
            if self._stop.is_set():
                break
            await self._wait_idle(profile, service=svc)

        # Wave 2: HH apply + LI network (after search/collect on each workspace).
        wait_services = []
        if want_hh_apply and has_hh:
            await self._start_job(
                profile=profile,
                service="hh",
                label="hh_apply",
                start_fn=self.runner.start_apply,
                started=started,
                skipped=skipped,
                errors=errors,
                wait_services=wait_services,
            )
        elif want_hh_apply:
            skipped.append("hh_apply")
        else:
            skipped.append("hh_apply")

        if want_li_net and has_li:
            await self._start_job(
                profile=profile,
                service="linkedin",
                label="li_network",
                start_fn=self.runner.start_linkedin_network,
                started=started,
                skipped=skipped,
                errors=errors,
                wait_services=wait_services,
            )
        elif want_li_net:
            skipped.append("li_network")
        else:
            skipped.append("li_network")

        for svc in list(wait_services):
            if self._stop.is_set():
                break
            await self._wait_idle(profile, service=svc)

        if sched.get("email_report_after_run"):
            try:
                report = await asyncio.to_thread(
                    generate_scheduled_report,
                    self.uow,
                    self.settings,
                    kind="work",
                    profile=profile,
                    scheduled=True,
                    email=True,
                )
                emailed = bool(report.get("emailed"))
            except Exception as e:
                log.warning("Post-parse report email failed: %s", e)
                errors.append(f"email:{e}")

        self.uow.journal.log(
            profile,
            "parse_scheduled_done",
            f"started={started} skipped={skipped} errors={errors} emailed={emailed}",
            payload={
                "started": started,
                "skipped": skipped,
                "errors": errors,
                "emailed": emailed,
                "cron_job_rules": sched.get("cron_job_rules"),
            },
        )
        return {
            "ok": not errors,
            "started": started,
            "skipped": skipped,
            "errors": errors,
            "emailed": emailed,
        }
