"""Email HTML/plain templates for SMTP alerts."""

from __future__ import annotations

from app.infrastructure.email_templates import (
    classify_alert_kind,
    render_alert_email,
    render_html_alert,
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
