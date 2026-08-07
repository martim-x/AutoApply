"""SMTP / alert adapters."""

from app.infrastructure.alerts.smtp import SmtpSender, send_smtp_alert
from app.infrastructure.email_templates import render_alert_email

__all__ = ["SmtpSender", "send_smtp_alert", "render_alert_email"]

