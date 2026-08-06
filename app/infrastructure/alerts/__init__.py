"""SMTP / alert adapters."""

from app.infrastructure.alerts.smtp import SmtpSender, send_smtp_alert

__all__ = ["SmtpSender", "send_smtp_alert"]
