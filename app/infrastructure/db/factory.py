"""Choose DB backend from DATABASE_URL."""

from __future__ import annotations

from typing import cast

from app.domain.ports import UnitOfWork
from app.infrastructure.settings import Settings, get_settings

from .sqlite_uow import SqliteUnitOfWork


def create_uow(settings: Settings | None = None) -> UnitOfWork:
    settings = settings or get_settings()
    if settings.is_sqlite():
        path = settings.sqlite_path()
        assert path is not None
        return cast(UnitOfWork, SqliteUnitOfWork(path))

    # Placeholder for future Postgres adapter:
    # from .postgres_uow import PostgresUnitOfWork
    # return PostgresUnitOfWork(settings.database_url)
    raise NotImplementedError(
        f"Backend for DATABASE_URL={settings.database_url!r} not implemented yet. "
        "Use sqlite:///... for now; Postgres adapter is planned via same UnitOfWork ports."
    )
