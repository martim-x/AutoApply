"""Application alert notifier — rate-limited SMTP + last-alert for UI."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from app.infrastructure.alerts.smtp import send_smtp_alert
from app.infrastructure.email_templates import render_alert_email
from app.infrastructure.settings import Settings

log = logging.getLogger(__name__)

# Events that mean "human must intervene / pause work"
CAPTCHA_EVENTS = frozenset({"captcha", "need_manual", "linkedin_checkpoint"})
ERROR_EVENTS = frozenset(
    {
        "error",
        "job_aborted",
        "search_abort",
        "linkedin_auth_wall",
        "linkedin_network_error",
        "linkedin_vacancies_error",
        "parse_schedule_error",
        "session_lost",
        "browser_crash",
    }
)
PARSE_FAIL_EVENTS = frozenset(
    {
        "serp_fail",
        "unit_failed",
        "parse_fail",
        "linkedin_nav_error",
    }
)


class AlertService:
    """
    notify(event, message, details) → journal-friendly SMTP with dedupe.

    Rate-limit: max 1 identical (profile, event, message) alert per window.
    Captcha/errors pause work at the call site; this layer only emails.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        send_fn: Callable[..., bool] | None = None,
    ) -> None:
        self.settings = settings
        self._send_fn = send_fn or send_smtp_alert
        self._lock = threading.Lock()
        self._recent: dict[str, float] = {}
        self.last_alert: dict[str, Any] | None = None

    def config_notifications(self) -> list[str]:
        """Soft-default notes when SMTP is enabled but incomplete."""
        return self.settings.parse_alert_config().get("notifications") or []

    def should_alert(self, event: str) -> bool:
        cfg = self.settings.parse_alert_config()
        if not cfg["enabled"]:
            return False
        ev = (event or "").strip().lower()
        if ev in CAPTCHA_EVENTS or ev.startswith("captcha"):
            return bool(cfg["on_captcha"])
        if ev in PARSE_FAIL_EVENTS or ev.startswith("parse_"):
            return bool(cfg["on_parse_fail"])
        if ev in ERROR_EVENTS or ev.startswith("error"):
            return bool(cfg["on_error"])
        # Unknown warn-level events: only if error alerts on
        return bool(cfg["on_error"])

    def notify(
        self,
        event: str,
        message: str = "",
        *,
        profile: str = "default",
        details: dict[str, Any] | None = None,
        force: bool = False,
    ) -> bool:
        """
        Send rate-limited SMTP alert. Always records last_alert for UI when
        the event is alertable (even if SMTP disabled — for UI preview).
        Returns True only when an email was actually sent.
        """
        event = (event or "error").strip() or "error"
        message = (message or "").strip()
        profile = (profile or "default").strip() or "default"
        details = details or {}

        record = {
            "profile": profile,
            "event": event,
            "message": message,
            "details": details,
            "ts": time.time(),
            "sent": False,
        }

        if not force and not self.should_alert(event):
            with self._lock:
                # Still surface captcha/error in UI even when that channel is off
                if event in CAPTCHA_EVENTS or event in ERROR_EVENTS:
                    self.last_alert = {**record, "skipped": "flag_off"}
            return False

        key = f"{profile}|{event}|{message[:120]}"
        window = int(
            getattr(self.settings, "alert_rate_limit_seconds", 600) or 600
        )
        now = time.time()
        with self._lock:
            last = self._recent.get(key, 0.0)
            if not force and window > 0 and (now - last) < window:
                self.last_alert = {**record, "skipped": "rate_limited"}
                return False
            self._recent[key] = now

        msg_short = message if len(message) <= 200 else message[:199] + "…"
        subject = f"[auto-apply-app] {event} · {profile}"
        if len(subject) > 120:
            subject = subject[:119] + "…"
        # Drop noisy dumps from the email; full text stays in journal/logs.
        email_details: dict[str, Any] = {}
        for k, v in list((details or {}).items())[:8]:
            key = str(k)
            if key.lower() in {"tb", "traceback"}:
                email_details[key] = str(v)[-280:]
            elif key.lower() in {"raw", "log", "dump"}:
                email_details[key] = str(v)[:280]
            else:
                email_details[key] = v
        body, html_body = render_alert_email(
            event=event,
            message=msg_short,
            profile=profile,
            details=email_details or None,
        )

        sent = False
        try:
            result = self._send_fn(
                self.settings,
                subject=subject,
                body=body,
                html_body=html_body,
            )
            if isinstance(result, tuple):
                sent = bool(result[0])
            else:
                sent = bool(result)
        except TypeError:
            # Tests / custom send_fn may only accept body=
            try:
                result = self._send_fn(self.settings, subject=subject, body=body)
                if isinstance(result, tuple):
                    sent = bool(result[0])
                else:
                    sent = bool(result)
            except Exception as e:
                log.warning("Alert notify failed: %s", e)
                sent = False
        except Exception as e:
            log.warning("Alert notify failed: %s", e)
            sent = False

        record["sent"] = sent
        with self._lock:
            self.last_alert = record
        return sent

    def notify_captcha(
        self,
        profile: str,
        message: str = "Captcha / verification required",
        *,
        details: dict[str, Any] | None = None,
    ) -> bool:
        return self.notify(
            "captcha", message, profile=profile, details=details
        )

    def notify_error(
        self,
        profile: str,
        message: str,
        *,
        event: str = "error",
        details: dict[str, Any] | None = None,
    ) -> bool:
        return self.notify(event, message, profile=profile, details=details)


_singleton: AlertService | None = None
_singleton_lock = threading.Lock()


def get_alert_service(settings: Settings | None = None) -> AlertService:
    """Process-wide AlertService (rate-limit state survives job threads)."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            if settings is None:
                from app.infrastructure.settings import get_settings

                settings = get_settings()
            _singleton = AlertService(settings)
        elif settings is not None:
            _singleton.settings = settings
        return _singleton


def reset_alert_service() -> None:
    """Test helper."""
    global _singleton
    with _singleton_lock:
        _singleton = None
