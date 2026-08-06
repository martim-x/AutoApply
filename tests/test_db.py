"""SQLite UnitOfWork tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.entities import Application, Vacancy
from app.domain.enums import ApplyStatus, FitCategory, JobStatus
from app.infrastructure.db.sqlite_uow import SqliteUnitOfWork


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


def test_rename_and_delete_profile(tmp_path: Path):
    db = SqliteUnitOfWork(tmp_path / "t_rename.sqlite")
    # Fresh DB bootstraps default only because empty
    assert {p.name for p in db.profiles.list_profiles()} == {"default"}

    db.profiles.ensure_profile("alpha")
    db.vacancies.upsert(
        Vacancy(
            profile="alpha",
            url="https://rabota.by/vacancy/42",
            title="dev",
            category=FitCategory.HIGH,
            score=90,
            filter_status="ok",
            apply_status=ApplyStatus.QUEUED,
        )
    )
    db.journal.log("alpha", "note", "hello")
    db.jobs.set_status("alpha", JobStatus.IDLE, "ok")

    renamed = db.profiles.rename_profile("alpha", "beta")
    assert renamed.name == "beta"
    assert db.vacancies.list_for_profile("beta")
    assert not db.vacancies.list_for_profile("alpha")
    assert db.journal.recent("beta", limit=5)

    # Delete bootstrap default while another profile exists → default stays gone
    selected = db.profiles.delete_profile("default")
    assert selected == "beta"
    names = {p.name for p in db.profiles.list_profiles()}
    assert names == {"beta"}

    # Re-open UoW must NOT resurrect default when profiles exist
    db2 = SqliteUnitOfWork(tmp_path / "t_rename.sqlite")
    assert {p.name for p in db2.profiles.list_profiles()} == {"beta"}

    # Deleting the last profile recreates empty default
    only = db2.profiles.delete_profile("beta")
    assert only == "default"
    assert {p.name for p in db2.profiles.list_profiles()} == {"default"}


def test_rename_conflict_with_existing(tmp_path: Path):
    db = SqliteUnitOfWork(tmp_path / "t_conflict.sqlite")
    db.profiles.ensure_profile("alpha")
    try:
        db.profiles.rename_profile("alpha", "default")
        assert False, "expected conflict with default"
    except ValueError:
        pass


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
