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


def _strip_env(value: Any) -> str:
    """Trim whitespace and optional wrapping quotes from Railway/raw env values."""
    s = str(value or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s


def _smtp_credentials(
    settings: Any,
) -> dict[str, Any] | None:
    """
    Resolve ALERT_SMTP_* (also used for scheduled PDF reports).
    Returns None when disabled or misconfigured.
    """
    if not getattr(settings, "alert_smtp_enabled", False):
        return None
    host = _strip_env(getattr(settings, "alert_smtp_host", None))
    mail_to = _strip_env(getattr(settings, "alert_smtp_to", None))
    mail_from = _strip_env(getattr(settings, "alert_smtp_from", None))
    user = _strip_env(getattr(settings, "alert_smtp_user", None))
    password = _strip_env(getattr(settings, "alert_smtp_password", None))
    if not host or not mail_to:
        log.warning("SMTP skipped: ALERT_SMTP_HOST / ALERT_SMTP_TO missing")
        return None
    if not mail_from:
        mail_from = user or mail_to
    try:
        port = int(_strip_env(getattr(settings, "alert_smtp_port", None)) or 587)
    except ValueError:
        port = 587
    return {
        "host": host,
        "mail_to": mail_to,
        "mail_from": mail_from,
        "port": port,
        "user": user,
        "password": password,
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
) -> tuple[bool, str]:
    """
    Send one email using ALERT_SMTP_* settings.
    Returns (ok, detail). detail explains skip/failure for journal.
    """
    creds = _smtp_credentials(settings)
    if creds is None:
        if not getattr(settings, "alert_smtp_enabled", False):
            return False, "ALERT_SMTP_ENABLED is false"
        return False, "ALERT_SMTP_HOST or ALERT_SMTP_TO missing"

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
        return True, "sent"
    except Exception as e:
        log.warning("SMTP alert failed: %s", e)
        return False, f"SMTP error: {e}"


def send_report_email(
    settings: Any,
    *,
    subject: str,
    body: str,
    html_body: str | None = None,
    pdf_path: str | Path | None = None,
    sender: SmtpSender | None = None,
) -> tuple[bool, str]:
    """
    Send a report email (HTML + optional PDF) via the same ALERT_SMTP_* channel.
    Returns (ok, detail).
    """
    attachments: list[Attachment] | None = None
    if pdf_path is not None:
        try:
            attachments = [attachment_from_path(pdf_path)]
        except OSError as e:
            log.warning("SMTP report: cannot read PDF %s: %s", pdf_path, e)
            return False, f"cannot read PDF: {e}"
    return send_smtp_alert(
        settings,
        subject=subject,
        body=body,
        html_body=html_body,
        attachments=attachments,
        sender=sender,
    )
