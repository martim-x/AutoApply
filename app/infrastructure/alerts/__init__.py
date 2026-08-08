"""SMTP / alert adapters."""

from app.infrastructure.alerts.smtp import (
    SmtpSender,
    attachment_from_path,
    send_report_email,
    send_smtp_alert,
)
from app.infrastructure.email_templates import render_alert_email, render_report_email

__all__ = [
    "SmtpSender",
    "attachment_from_path",
    "send_smtp_alert",
    "send_report_email",
    "render_alert_email",
    "render_report_email",
]

