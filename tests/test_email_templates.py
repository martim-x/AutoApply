"""Email HTML/plain templates for SMTP alerts and reports."""

from __future__ import annotations

from app.application.reports import ReportPayload, ReportTheme
from app.infrastructure.email_templates import (
    classify_alert_kind,
    render_alert_email,
    render_html_alert,
    render_report_email,
)


def test_render_alert_contains_brand_and_dark_media_query():
    plain, html = render_alert_email(
        event="error",
        message="Chromium не запустился",
        profile="default",
        details={"hint": "HEADLESS=true"},
    )
    assert "auto-apply-app" in plain
    assert "auto-apply-app" in html
    assert "prefers-color-scheme: dark" in html
    assert "Chromium не запустился" in html
    assert "HEADLESS=true" in html


def test_html_escapes_user_content():
    html = render_html_alert(
        kind="error",
        title='<script>alert(1)</script>',
        message='Boom & <b>bold</b>',
        profile='p"><img>',
        event="error",
        details={"raw": "<iframe>"},
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert "&lt;b&gt;" in html
    assert "&lt;iframe&gt;" in html
    assert 'p"><img>' not in html


def test_details_truncated_for_long_dumps():
    dump = "line\n" + ("x" * 2000)
    plain, html = render_alert_email(
        event="job_aborted",
        message="fail",
        details={"tb": dump, "raw": dump},
    )
    assert "xxxx" not in plain[-50:]  # truncated
    assert len(plain) < 2500
    assert dump not in html
    assert "…" in plain or "…" in html


def test_classify_kinds():
    assert classify_alert_kind("captcha") == "captcha"
    assert classify_alert_kind("need_manual") == "captcha"
    assert classify_alert_kind("job_aborted") == "job"
    assert classify_alert_kind("parse_fail") == "job"
    assert classify_alert_kind("error") == "error"
    assert classify_alert_kind("browser_crash") == "error"
    assert classify_alert_kind("info") == "notification"


def test_render_report_email_html_page_with_stats():
    payload = ReportPayload(
        kind="work",
        title="Отчёт о проделанной работе",
        profile="default",
        app_name="auto-apply-app",
        generated_at=1_700_000_000.0,
        themes=[
            ReportTheme(
                title="Статистика работы",
                blocks=[
                    {
                        "type": "kv",
                        "title": "Категории",
                        "rows": [
                            ("HIGH", "3"),
                            ("MEDIUM", "2"),
                            ("LOW", "1"),
                            ("В очереди", "4"),
                        ],
                    },
                    {
                        "type": "table",
                        "title": "Топ",
                        "headers": ["Кат.", "Score", "Статус", "Вакансия"],
                        "rows": [["HIGH", "12", "queued", "Python <b>dev</b>"]],
                    },
                ],
            )
        ],
    )
    plain, html = render_report_email(payload, pdf_name="report.pdf")
    assert "auto-apply-app" in plain
    assert "HIGH: 3" in plain or "HIGH" in plain
    assert "report.pdf" in plain
    assert "auto-apply-app" in html
    assert "prefers-color-scheme: dark" in html
    assert "Отчёт" in html
    assert "#1a7a38" in html  # HIGH accent
    assert "&lt;b&gt;" in html  # escaped vacancy title
    assert "report.pdf" in html
