"""SMTP alerts + captcha stop behavior (mocked send)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.application.alerts import (
    AlertService,
    reset_alert_service,
)
from app.domain.enums import JobStatus
from app.infrastructure.alerts.smtp import (
    SmtpSender,
    attachment_from_path,
    send_report_email,
    send_smtp_alert,
)
from app.infrastructure.browser.gateway import PlaywrightBrowserGateway
from app.infrastructure.db.sqlite_uow import SqliteUnitOfWork
from app.infrastructure.settings import Settings


def _settings(**kwargs) -> Settings:
    base = dict(
        alert_smtp_enabled=True,
        alert_smtp_host="smtp.test",
        alert_smtp_port=587,
        alert_smtp_user="u",
        alert_smtp_password="p",
        alert_smtp_from="from@test",
        alert_smtp_to="to@test",
        alert_smtp_tls=True,
        alert_on_error=True,
        alert_on_captcha=True,
        alert_on_parse_fail=True,
        alert_rate_limit_seconds=600,
    )
    base.update(kwargs)
    return Settings(**base)


def setup_function() -> None:
    reset_alert_service()


def test_parse_alert_config_soft_defaults():
    s = _settings(alert_smtp_host="", alert_smtp_to="")
    cfg = s.parse_alert_config()
    assert cfg["enabled"] is True
    assert any("HOST" in n for n in cfg["notifications"])
    assert any("TO" in n for n in cfg["notifications"])


def test_send_smtp_alert_calls_sender():
    s = _settings()
    sender = MagicMock(spec=SmtpSender)
    ok = send_smtp_alert(
        s, subject="sub", body="body", html_body="<p>hi</p>", sender=sender
    )
    assert ok is True
    sender.send.assert_called_once()
    kwargs = sender.send.call_args.kwargs
    assert kwargs["host"] == "smtp.test"
    assert kwargs["mail_to"] == "to@test"
    assert kwargs["subject"] == "sub"
    assert kwargs["html_body"] == "<p>hi</p>"


def test_alert_service_sends_html():
    captured: dict = {}

    def fake_send(settings, *, subject, body, html_body=None):
        captured["subject"] = subject
        captured["body"] = body
        captured["html_body"] = html_body
        return True

    svc = AlertService(_settings(), send_fn=fake_send)
    assert svc.notify("error", "boom <x>", profile="default") is True
    assert "auto-apply-app" in captured["body"]
    assert captured["html_body"]
    assert "auto-apply-app" in captured["html_body"]
    assert "prefers-color-scheme: dark" in captured["html_body"]
    assert "&lt;x&gt;" in captured["html_body"]


def test_send_smtp_skipped_when_disabled():
    s = _settings(alert_smtp_enabled=False)
    sender = MagicMock(spec=SmtpSender)
    assert send_smtp_alert(s, subject="x", body="y", sender=sender) is False
    sender.send.assert_not_called()


def test_attachment_from_path_and_report_email(tmp_path):
    pdf = tmp_path / "auto-apply-app-work-default.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    name, data, maintype, subtype = attachment_from_path(pdf)
    assert name.endswith(".pdf")
    assert data.startswith(b"%PDF")
    assert maintype == "application"
    assert subtype == "pdf"

    sender = MagicMock(spec=SmtpSender)
    ok = send_report_email(
        _settings(),
        subject="report",
        body="plain",
        html_body="<p>hi</p>",
        pdf_path=pdf,
        sender=sender,
    )
    assert ok is True
    kwargs = sender.send.call_args.kwargs
    assert kwargs["html_body"] == "<p>hi</p>"
    assert kwargs["attachments"]
    assert kwargs["attachments"][0][0] == pdf.name
    assert kwargs["attachments"][0][1] == b"%PDF-1.4 fake"


def test_alert_service_rate_limit():
    sent: list[str] = []

    def fake_send(settings, *, subject, body):
        sent.append(subject)
        return True

    svc = AlertService(_settings(alert_rate_limit_seconds=600), send_fn=fake_send)
    assert svc.notify("error", "boom", profile="default") is True
    assert svc.notify("error", "boom", profile="default") is False
    assert len(sent) == 1
    assert svc.last_alert is not None
    assert svc.last_alert["skipped"] == "rate_limited"


def test_alert_service_respects_flags():
    sent: list[str] = []

    def fake_send(settings, *, subject, body):
        sent.append(subject)
        return True

    svc = AlertService(
        _settings(alert_on_captcha=False, alert_on_error=True),
        send_fn=fake_send,
    )
    assert svc.notify("captcha", "see captcha", profile="p") is False
    assert svc.notify("error", "fail", profile="p") is True
    assert len(sent) == 1


def test_pause_for_blocker_sets_waiting_user_and_alerts(tmp_path):
    db = SqliteUnitOfWork(tmp_path / "t.sqlite")
    db.profiles.ensure_profile("default")
    sent: list[tuple[str, str]] = []

    def fake_send(settings, *, subject, body):
        sent.append((subject, body))
        return True

    alerts = AlertService(_settings(), send_fn=fake_send)
    gw = PlaywrightBrowserGateway(db, _settings(), alerts=alerts)
    gw._pause_for_blocker("default", "captcha", context="vacancy X")

    st = db.jobs.get_status("default")
    assert st.status == JobStatus.WAITING_USER
    assert "captcha" in st.message.lower() or "человек" in st.message.lower()
    logs = db.journal.recent("default", limit=5)
    assert any(e.event == "captcha" for e in logs)
    assert len(sent) == 1
    assert "captcha" in sent[0][0].lower()


def test_pause_need_manual_also_alerts(tmp_path):
    db = SqliteUnitOfWork(tmp_path / "t2.sqlite")
    db.profiles.ensure_profile("default")
    sent: list[str] = []

    def fake_send(settings, *, subject, body):
        sent.append(subject)
        return True

    alerts = AlertService(_settings(), send_fn=fake_send)
    gw = PlaywrightBrowserGateway(db, _settings(), alerts=alerts)
    gw._pause_for_blocker("default", "need_manual")
    assert db.jobs.get_status("default").status == JobStatus.WAITING_USER
    assert sent


def test_safe_run_job_aborted_keeps_data(tmp_path):
    from app.infrastructure.browser.gateway import safe_run

    db = SqliteUnitOfWork(tmp_path / "t3.sqlite")
    db.profiles.ensure_profile("default")
    from app.domain.entities import Vacancy
    from app.domain.enums import ApplyStatus, FitCategory

    db.vacancies.upsert(
        Vacancy(
            profile="default",
            url="https://rabota.by/vacancy/1",
            vacancy_id="1",
            title="kept",
            category=FitCategory.HIGH,
            apply_status=ApplyStatus.QUEUED,
        )
    )
    sent: list[str] = []

    def fake_send(settings, *, subject, body):
        sent.append(subject)
        return True

    alerts = AlertService(_settings(), send_fn=fake_send)

    def boom():
        raise RuntimeError("browser crashed")

    safe_run(boom, db, "default", alerts=alerts)
    assert db.jobs.get_status("default").status == JobStatus.ERROR
    assert db.vacancies.exists("default", vacancy_id="1")
    events = [e.event for e in db.journal.recent("default", limit=10)]
    assert "job_aborted" in events
    assert any("job_aborted" in s.lower() or "error" in s.lower() for s in sent)


def test_stop_flag_after_captcha_pause(tmp_path):
    """Captcha path should set WAITING_USER; caller stops the flag."""
    from app.infrastructure.browser.job_runner import StopFlag

    db = SqliteUnitOfWork(tmp_path / "t4.sqlite")
    db.profiles.ensure_profile("default")
    alerts = AlertService(_settings(), send_fn=lambda *a, **k: True)
    gw = PlaywrightBrowserGateway(db, _settings(), alerts=alerts)
    flag = StopFlag()
    gw._pause_for_blocker("default", "captcha")
    flag.stop()
    assert flag.stopped
    assert db.jobs.get_status("default").status == JobStatus.WAITING_USER
