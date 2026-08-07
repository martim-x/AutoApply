"""SQLite UnitOfWork tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.entities import Application, Vacancy
from app.domain.enums import ApplyStatus, FitCategory, JobStatus
from app.infrastructure.db.sqlite_uow import (
    SqliteUnitOfWork,
    adopt_legacy_sqlite_if_needed,
    prepare_sqlite_file,
)


def test_prepare_sqlite_file_mkdir_and_fresh_flag(tmp_path: Path):
    path = tmp_path / "sub" / "a.sqlite"
    assert prepare_sqlite_file(path) is True
    assert path.parent.is_dir()
    path.write_bytes(b"")
    assert prepare_sqlite_file(path) is False
    assert prepare_sqlite_file(path, reset=True) is True


def test_adopt_legacy_sqlite_renames_old_file(tmp_path: Path):
    legacy = tmp_path / "rabota_apply.sqlite"
    legacy.write_bytes(b"legacy-db")
    Path(f"{legacy}-wal").write_bytes(b"wal")
    target = tmp_path / "auto_apply_app.sqlite"
    assert adopt_legacy_sqlite_if_needed(target) is True
    assert target.read_bytes() == b"legacy-db"
    assert not legacy.exists()
    assert Path(f"{target}-wal").read_bytes() == b"wal"
    assert prepare_sqlite_file(target) is False


def test_adopt_legacy_skipped_when_target_exists(tmp_path: Path):
    legacy = tmp_path / "rabota_apply.sqlite"
    legacy.write_bytes(b"old")
    target = tmp_path / "auto_apply_app.sqlite"
    target.write_bytes(b"new")
    assert adopt_legacy_sqlite_if_needed(target) is False
    assert legacy.read_bytes() == b"old"
    assert target.read_bytes() == b"new"


def test_creates_empty_db_when_missing(tmp_path: Path):
    path = tmp_path / "nested" / "fresh.sqlite"
    assert not path.exists()
    db = SqliteUnitOfWork(path)
    assert path.exists()
    assert {p.name for p in db.profiles.list_profiles()} == {"default"}
    assert db.vacancies.list_for_profile("default") == []
    assert db.applications.stats("default")["applied"] == 0


def test_preserves_existing_db_without_reset(tmp_path: Path):
    path = tmp_path / "keep.sqlite"
    db = SqliteUnitOfWork(path)
    db.profiles.ensure_profile("keep_me")
    db.journal.log("keep_me", "seed", "data")
    db2 = SqliteUnitOfWork(path)
    assert {p.name for p in db2.profiles.list_profiles()} >= {"default", "keep_me"}
    assert db2.journal.recent("keep_me", limit=1)[0].event == "seed"


def test_reset_db_wipes_and_recreates_empty(tmp_path: Path):
    path = tmp_path / "wipe.sqlite"
    db = SqliteUnitOfWork(path)
    db.profiles.ensure_profile("old")
    db.journal.log("old", "noise", "x")
    assert path.exists()

    db2 = SqliteUnitOfWork(path, reset=True)
    names = {p.name for p in db2.profiles.list_profiles()}
    assert names == {"default"}
    assert db2.journal.recent("old", limit=5) == []
    assert db2.vacancies.list_for_profile("default") == []


def test_create_uow_respects_reset_db_setting(tmp_path: Path, monkeypatch):
    from app.infrastructure.db import create_uow
    from app.infrastructure.settings import Settings, get_settings

    data = tmp_path / "data"
    db_path = data / "t.sqlite"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("RESET_DB", "false")
    get_settings.cache_clear()

    uow = create_uow(Settings())
    uow.profiles.ensure_profile("alive")
    get_settings.cache_clear()

    monkeypatch.setenv("RESET_DB", "true")
    get_settings.cache_clear()
    uow2 = create_uow(Settings())
    assert {p.name for p in uow2.profiles.list_profiles()} == {"default"}
    get_settings.cache_clear()


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

    capped = db.vacancies.next_queued("p1", limit=2)
    assert [v.title for v in capped] == ["high", "med"]


def test_next_queued_skips_non_ok_but_keeps_all_categories(tmp_path: Path):
    """Apply queue is all found (filter ok), not HIGH-only."""
    db = SqliteUnitOfWork(tmp_path / "t_all_cats.sqlite")
    db.profiles.ensure_profile("p1")
    for title, cat, filt in (
        ("hi", FitCategory.HIGH, "ok"),
        ("lo", FitCategory.LOW, "ok"),
        ("bad", FitCategory.MEDIUM, "filtered:gov"),
        ("med", FitCategory.MEDIUM, "ok"),
    ):
        db.vacancies.upsert(
            Vacancy(
                profile="p1",
                url=f"https://rabota.by/vacancy/{title}",
                title=title,
                category=cat,
                score=50,
                filter_status=filt,
                apply_status=ApplyStatus.QUEUED,
            )
        )
    q = db.vacancies.next_queued("p1", limit=100)
    assert [v.title for v in q] == ["hi", "med", "lo"]


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
    assert logs[0].service == "hh"

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


def test_journal_service_separation(tmp_path: Path):
    db = SqliteUnitOfWork(tmp_path / "journal_svc.sqlite")
    db.profiles.ensure_profile("default")
    db.journal.log("default", "search_done", "hh ok")
    db.journal.log("default", "linkedin_network_done", "li ok")
    db.journal.log(
        "default", "config_default", "li note", service="linkedin"
    )
    db.journal.log("default", "filtered:duplicate", "hh dup", service="hh")

    hh = db.journal.recent("default", limit=20, service="hh")
    li = db.journal.recent("default", limit=20, service="linkedin")
    assert {e.event for e in hh} == {"search_done", "filtered:duplicate"}
    assert {e.event for e in li} == {"linkedin_network_done", "config_default"}
    assert all(e.service == "hh" for e in hh)
    assert all(e.service == "linkedin" for e in li)

    # inference from linkedin_ prefix without explicit service
    inferred = db.journal.recent("default", limit=1, service="linkedin")
    assert inferred[0].event in {"linkedin_network_done", "config_default"}


def test_journal_service_migration_backfill(tmp_path: Path):
    """Existing DBs without service column get column + linkedin_ backfill."""
    import sqlite3

    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as c:
        c.executescript(
            """
            CREATE TABLE journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                profile TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                event TEXT NOT NULL,
                message TEXT,
                payload TEXT
            );
            INSERT INTO journal(ts, profile, level, event, message, payload)
            VALUES (1, 'default', 'info', 'search_done', 'hh', '{}');
            INSERT INTO journal(ts, profile, level, event, message, payload)
            VALUES (2, 'default', 'info', 'linkedin_login_start', 'li', '{}');
            """
        )
    db = SqliteUnitOfWork(path)
    hh = db.journal.recent("default", limit=10, service="hh")
    li = db.journal.recent("default", limit=10, service="linkedin")
    assert [e.event for e in hh] == ["search_done"]
    assert [e.event for e in li] == ["linkedin_login_start"]
