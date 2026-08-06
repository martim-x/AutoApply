"""Sync SMTP sender (stdlib smtplib) — short timeouts for one Railway process."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any

log = logging.getLogger(__name__)

# Keep SMTP brief so a hung mail server does not stall the worker long.
SMTP_TIMEOUT_SEC = 12


class SmtpSender:
    """Thin wrapper around smtplib for unit-test mocking."""

    def send(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        mail_from: str,
        mail_to: str,
        subject: str,
        body: str,
        use_tls: bool = True,
        timeout: float = SMTP_TIMEOUT_SEC,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = mail_from
        msg["To"] = mail_to
        msg.set_content(body)

        # Port 465 → implicit SSL (e.g. smtp.yandex.ru); 587 → STARTTLS.
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        elif use_tls:
            with smtplib.SMTP(host, port, timeout=timeout) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)


def send_smtp_alert(
    settings: Any,
    *,
    subject: str,
    body: str,
    sender: SmtpSender | None = None,
) -> bool:
    """
    Send one email using ALERT_SMTP_* settings.
    Returns True if sent, False if skipped/disabled/misconfigured.
    """
    if not getattr(settings, "alert_smtp_enabled", False):
        return False
    host = (getattr(settings, "alert_smtp_host", None) or "").strip()
    mail_to = (getattr(settings, "alert_smtp_to", None) or "").strip()
    mail_from = (getattr(settings, "alert_smtp_from", None) or "").strip()
    if not host or not mail_to:
        log.warning("SMTP alert skipped: ALERT_SMTP_HOST / ALERT_SMTP_TO missing")
        return False
    if not mail_from:
        mail_from = (getattr(settings, "alert_smtp_user", None) or "").strip() or mail_to

    port = int(getattr(settings, "alert_smtp_port", 587) or 587)
    user = (getattr(settings, "alert_smtp_user", None) or "").strip()
    password = getattr(settings, "alert_smtp_password", None) or ""
    use_tls = bool(getattr(settings, "alert_smtp_tls", True))

    smtp = sender or SmtpSender()
    try:
        smtp.send(
            host=host,
            port=port,
            user=user,
            password=password,
            mail_from=mail_from,
            mail_to=mail_to,
            subject=subject,
            body=body,
            use_tls=use_tls,
        )
        return True
    except Exception as e:
        log.warning("SMTP alert failed: %s", e)
        return False
