"""Sync SMTP sender (stdlib smtplib) — short timeouts for one Railway process."""

from __future__ import annotations

import logging
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Keep SMTP brief so a hung mail server does not stall the worker long.
SMTP_TIMEOUT_SEC = 12

# (filename, raw_bytes, maintype, subtype)
Attachment = tuple[str, bytes, str, str]


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
        html_body: str | None = None,
        attachments: list[Attachment] | None = None,
        use_tls: bool = True,
        timeout: float = SMTP_TIMEOUT_SEC,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = mail_from
        msg["To"] = mail_to
        msg.set_content(body or "")
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        for filename, data, maintype, subtype in attachments or []:
            msg.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype,
                filename=filename,
            )

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


def attachment_from_path(path: str | Path) -> Attachment:
    """Build an SmtpSender attachment tuple from a filesystem path."""
    p = Path(path)
    data = p.read_bytes()
    guessed, _ = mimetypes.guess_type(p.name)
    if guessed and "/" in guessed:
        maintype, subtype = guessed.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"
    return (p.name, data, maintype, subtype)


def _smtp_credentials(
    settings: Any,
) -> dict[str, Any] | None:
    """
    Resolve ALERT_SMTP_* (also used for scheduled PDF reports).
    Returns None when disabled or misconfigured.
    """
    if not getattr(settings, "alert_smtp_enabled", False):
        return None
    host = (getattr(settings, "alert_smtp_host", None) or "").strip()
    mail_to = (getattr(settings, "alert_smtp_to", None) or "").strip()
    mail_from = (getattr(settings, "alert_smtp_from", None) or "").strip()
    if not host or not mail_to:
        log.warning("SMTP skipped: ALERT_SMTP_HOST / ALERT_SMTP_TO missing")
        return None
    if not mail_from:
        mail_from = (getattr(settings, "alert_smtp_user", None) or "").strip() or mail_to
    return {
        "host": host,
        "mail_to": mail_to,
        "mail_from": mail_from,
        "port": int(getattr(settings, "alert_smtp_port", 587) or 587),
        "user": (getattr(settings, "alert_smtp_user", None) or "").strip(),
        "password": getattr(settings, "alert_smtp_password", None) or "",
        "use_tls": bool(getattr(settings, "alert_smtp_tls", True)),
    }


def send_smtp_alert(
    settings: Any,
    *,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[Attachment] | None = None,
    sender: SmtpSender | None = None,
) -> bool:
    """
    Send one email using ALERT_SMTP_* settings.
    Returns True if sent, False if skipped/disabled/misconfigured.
    """
    creds = _smtp_credentials(settings)
    if creds is None:
        return False

    smtp = sender or SmtpSender()
    try:
        smtp.send(
            host=creds["host"],
            port=creds["port"],
            user=creds["user"],
            password=creds["password"],
            mail_from=creds["mail_from"],
            mail_to=creds["mail_to"],
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=attachments,
            use_tls=creds["use_tls"],
        )
        return True
    except Exception as e:
        log.warning("SMTP alert failed: %s", e)
        return False


def send_report_email(
    settings: Any,
    *,
    subject: str,
    body: str,
    html_body: str | None = None,
    pdf_path: str | Path | None = None,
    sender: SmtpSender | None = None,
) -> bool:
    """
    Send a report email (HTML + optional PDF) via the same ALERT_SMTP_* channel.
    Returns True if sent, False if skipped/disabled/misconfigured/failed.
    """
    attachments: list[Attachment] | None = None
    if pdf_path is not None:
        try:
            attachments = [attachment_from_path(pdf_path)]
        except OSError as e:
            log.warning("SMTP report: cannot read PDF %s: %s", pdf_path, e)
            return False
    return send_smtp_alert(
        settings,
        subject=subject,
        body=body,
        html_body=html_body,
        attachments=attachments,
        sender=sender,
    )
