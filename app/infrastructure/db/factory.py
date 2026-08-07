"""Choose DB backend from DATABASE_URL (SQLite or Postgres)."""

from __future__ import annotations

from typing import cast

from app.domain.ports import UnitOfWork
from app.infrastructure.settings import Settings, get_settings

from .postgres_uow import PostgresUnitOfWork
from .sqlite_uow import SqliteUnitOfWork


def create_uow(settings: Settings | None = None) -> UnitOfWork:
    """Open UnitOfWork; create empty schema if missing (SQLite file / Postgres DDL)."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    if settings.is_sqlite():
        path = settings.sqlite_path()
        assert path is not None
        return cast(
            UnitOfWork,
            SqliteUnitOfWork(path, reset=bool(settings.reset_db)),
        )

    if settings.is_postgres():
        return cast(
            UnitOfWork,
            PostgresUnitOfWork(
                settings.postgres_url(),
                reset=bool(settings.reset_db),
                echo=bool(settings.debug),
            ),
        )

    raise NotImplementedError(
        f"Backend for DATABASE_URL={settings.database_url!r} not implemented. "
        "Use sqlite:///… or postgresql://… / postgresql+psycopg://…"
    )
