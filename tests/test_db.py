"""SQLite UnitOfWork tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.entities import Application, Vacancy  # noqa: E402
from app.domain.enums import ApplyStatus, FitCategory, JobStatus  # noqa: E402
from app.infrastructure.db.sqlite_uow import SqliteUnitOfWork  # noqa: E402


def test_profile_and_vacancy_priority(tmp_path: Path):
    db = SqliteUnitOfWork(tmp_path / "t.sqlite")
    db.profiles.ensure_profile("p1")

    db.vacancies.upsert(
        Vacancy(
            profile="p1",
            url="https://rabota.by/vacancy/1",
            title="low",
            category=FitCategory.LOW,
            score=10,
            filter_status="ok",
            apply_status=ApplyStatus.QUEUED,
        )
    )
    db.vacancies.upsert(
        Vacancy(
            profile="p1",
            url="https://rabota.by/vacancy/2",
            title="high",
            category=FitCategory.HIGH,
            score=95,
            filter_status="ok",
            apply_status=ApplyStatus.QUEUED,
        )
    )
    db.vacancies.upsert(
        Vacancy(
            profile="p1",
            url="https://rabota.by/vacancy/3",
            title="med",
            category=FitCategory.MEDIUM,
            score=60,
            filter_status="ok",
            apply_status=ApplyStatus.QUEUED,
        )
    )

    q = db.vacancies.next_queued("p1")
    assert [v.title for v in q] == ["high", "med", "low"]


def test_journal_and_status(tmp_path: Path):
    db = SqliteUnitOfWork(tmp_path / "t2.sqlite")
    db.profiles.ensure_profile("default")
    db.jobs.set_status("default", JobStatus.SEARCHING, "go")
    st = db.jobs.get_status("default")
    assert st.status == JobStatus.SEARCHING
    assert st.message == "go"

    db.journal.log("default", "test", "hello")
    logs = db.journal.recent("default", limit=5)
    assert logs[0].event == "test"

    db.applications.record(
        Application(
            profile="default",
            vacancy_url="https://rabota.by/vacancy/9",
            status="applied",
            title="x",
        )
    )
    assert db.applications.already_applied("default", "https://rabota.by/vacancy/9")
    db.vacancies.upsert(
        Vacancy(
            profile="default",
            url="https://rabota.by/vacancy/9",
            vacancy_id="9",
            title="x",
            category=FitCategory.HIGH,
            score=90,
            filter_status="ok",
            apply_status=ApplyStatus.QUEUED,
        )
    )
    assert db.vacancies.exists("default", url="https://rabota.by/vacancy/9")
    assert db.vacancies.exists("default", vacancy_id="9")
    assert not db.vacancies.exists("default", vacancy_id="404")
    urls, ids = db.vacancies.known_keys("default")
    assert "https://rabota.by/vacancy/9" in urls
    assert "9" in ids
    stats = db.stats("default")
    assert stats["applied"] == 1
