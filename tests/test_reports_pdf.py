"""PDF report assembly + rendering smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.reports import REPORT_KINDS, assemble_report, normalize_kind
from app.infrastructure.db.sqlite_uow import SqliteUnitOfWork
from app.infrastructure.reports.pdf import render_report_pdf, write_report_pdf
from app.infrastructure.settings import Settings


@pytest.fixture()
def uow(tmp_path: Path) -> SqliteUnitOfWork:
    return SqliteUnitOfWork(tmp_path / "test.sqlite")


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    s = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'test.sqlite'}",
    )
    s.ensure_dirs()
    return s


def test_normalize_kind() -> None:
    assert normalize_kind("work") == "work"
    assert normalize_kind("QUEUE.PDF") == "queue"
    with pytest.raises(ValueError):
        normalize_kind("nope")


def test_assemble_and_render_all_kinds(uow: SqliteUnitOfWork, settings: Settings, tmp_path: Path) -> None:
    for kind in REPORT_KINDS:
        payload = assemble_report(uow, settings, kind, "default")
        assert payload.kind == kind
        assert payload.themes
        out = tmp_path / f"{kind}.pdf"
        write_report_pdf(payload, out)
        assert out.stat().st_size > 500
        assert out.read_bytes()[:4] == b"%PDF"


def test_render_temp_file(uow: SqliteUnitOfWork, settings: Settings) -> None:
    payload = assemble_report(uow, settings, "work", "default")
    path = render_report_pdf(payload)
    try:
        assert path.is_file()
        assert path.read_bytes()[:4] == b"%PDF"
    finally:
        path.unlink(missing_ok=True)


def test_generate_scheduled_report_emails_without_crashing(
    uow: SqliteUnitOfWork, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.infrastructure import scheduler as sched_mod

    settings.alert_smtp_enabled = True
    settings.alert_smtp_host = "smtp.test"
    settings.alert_smtp_to = "to@test"
    settings.alert_smtp_from = "from@test"

    calls: list[dict] = []

    def fake_send(settings_obj, *, subject, body, html_body=None, pdf_path=None, sender=None):
        calls.append(
            {
                "subject": subject,
                "html": html_body,
                "pdf": str(pdf_path) if pdf_path else None,
            }
        )
        return True

    monkeypatch.setattr(
        "app.infrastructure.alerts.smtp.send_report_email",
        fake_send,
    )
    result = sched_mod.generate_scheduled_report(
        uow, settings, kind="work", profile="default", scheduled=True
    )
    assert result["ok"] is True
    assert Path(result["path"]).is_file()
    assert result["emailed"] is True
    assert calls and calls[0]["html"]
    assert "auto-apply-app" in (calls[0]["html"] or "")
    events = [e.event for e in uow.journal.recent("default", limit=20)]
    assert "report_generated" in events
    assert "report_emailed" in events


def test_generate_report_smtp_failure_keeps_pdf(
    uow: SqliteUnitOfWork, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.infrastructure import scheduler as sched_mod

    settings.alert_smtp_enabled = True
    settings.alert_smtp_host = "smtp.test"
    settings.alert_smtp_to = "to@test"

    def boom(*_a, **_k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.infrastructure.alerts.smtp.send_report_email", boom)
    result = sched_mod.generate_scheduled_report(
        uow, settings, kind="work", profile="default", scheduled=True
    )
    assert result["ok"] is True
    assert Path(result["path"]).is_file()
    assert result["emailed"] is False
    events = [e.event for e in uow.journal.recent("default", limit=20)]
    assert "report_email_error" in events
