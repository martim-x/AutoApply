"""Postgres URL helpers + optional live integration tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.entities import Vacancy
from app.domain.enums import ApplyStatus, FitCategory
from app.infrastructure.db.factory import create_uow
from app.infrastructure.db.postgres_uow import (
    PostgresUnitOfWork,
    normalize_postgres_url,
)
from app.infrastructure.settings import Settings


def test_normalize_postgres_url_variants():
    assert normalize_postgres_url("postgresql://u:p@h:5432/db").startswith(
        "postgresql+psycopg://"
    )
    assert normalize_postgres_url("postgres://u:p@h/db").startswith(
        "postgresql+psycopg://"
    )
    assert (
        normalize_postgres_url("postgresql+psycopg://u:p@h/db")
        == "postgresql+psycopg://u:p@h/db"
    )
    with pytest.raises(ValueError):
        normalize_postgres_url("postgresql+asyncpg://u:p@h/db")
    with pytest.raises(ValueError):
        normalize_postgres_url("mysql://x")


def test_settings_is_postgres_and_url():
    s = Settings(
        database_url="postgresql://user:pass@localhost:5432/app",
        _env_file=None,
    )
    assert s.is_postgres()
    assert not s.is_sqlite()
    assert s.postgres_url().startswith("postgresql+psycopg://")


def test_factory_rejects_unknown_backend():
    s = Settings(database_url="mysql://localhost/x", _env_file=None)
    with pytest.raises(NotImplementedError):
        create_uow(s)


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL=postgresql://… to run live Postgres tests",
)
def test_postgres_uow_roundtrip():
    url = os.environ["TEST_DATABASE_URL"]
    uow = PostgresUnitOfWork(url, reset=True)
    try:
        profile = uow.profiles.ensure_profile("pg_test").name
        vid = uow.vacancies.upsert(
            Vacancy(
                profile=profile,
                vacancy_id="1",
                url="https://example.com/v/1",
                title="Python Dev",
                category=FitCategory.MEDIUM,
                score=10,
                filter_status="ok",
                apply_status=ApplyStatus.QUEUED,
            )
        )
        assert vid > 0
        items = uow.vacancies.list_for_profile(profile)
        assert len(items) == 1
        assert items[0].category == FitCategory.MEDIUM
        uow.journal.log(profile, "test", "hello", service="hh")
        logs = uow.journal.recent(profile, service="hh", limit=5)
        assert logs[0].event == "test"
        assert uow.stats(profile)["medium"] == 1
    finally:
        uow.dispose()
