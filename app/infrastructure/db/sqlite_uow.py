"""SQLite implementation of UnitOfWork / repositories."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.domain.entities import (
    Application,
    JobState,
    JournalEntry,
    LinkedInContact,
    LinkedInVacancyLink,
    Profile,
    Vacancy,
    normalize_journal_service,
)
from app.domain.enums import ApplyStatus, FitCategory, JobStatus

log = logging.getLogger(__name__)

LEGACY_SQLITE_BASENAME = "rabota_apply.sqlite"


def unlink_sqlite_files(path: Path) -> None:
    """Remove SQLite main DB and sidecar WAL/SHM files if present."""
    path = Path(path)
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists() and candidate.is_file():
            candidate.unlink()


def adopt_legacy_sqlite_if_needed(path: Path) -> bool:
    """
    If the configured DB path is missing but a legacy rabota_apply.sqlite
    sits in the same directory, rename it (and WAL/SHM sidecars) into place.

    Returns True when a rename happened.
    """
    path = Path(path)
    if path.exists():
        return False
    legacy = path.parent / LEGACY_SQLITE_BASENAME
    if not legacy.is_file():
        return False
    try:
        if legacy.resolve() == path.resolve():
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Adopting legacy SQLite database: %s → %s", legacy, path)
    legacy.rename(path)
    for suffix in ("-wal", "-shm"):
        old_side = Path(f"{legacy}{suffix}")
        new_side = Path(f"{path}{suffix}")
        if old_side.is_file() and not new_side.exists():
            old_side.rename(new_side)
    return True


def prepare_sqlite_file(path: Path, *, reset: bool = False) -> bool:
    """
    Ensure parent directory exists; optionally wipe an existing DB.

    Returns True when a brand-new empty DB will be created (missing file
    or wiped via reset). Does not leave leftover requirement to copy a
    local DB into Docker/Fly volumes — schema is applied on connect.

    Before creating a fresh file, adopts legacy rabota_apply.sqlite if present.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not reset:
        adopt_legacy_sqlite_if_needed(path)
    if reset and (path.exists() or Path(f"{path}-wal").exists()):
        log.warning("RESET_DB=true — deleting SQLite at %s", path)
        unlink_sqlite_files(path)
        return True
    return not path.exists()


class SqliteUnitOfWork:
    def __init__(self, path: Path, *, reset: bool = False) -> None:
        self.path = Path(path)
        fresh = prepare_sqlite_file(self.path, reset=reset)
        self.profiles = _ProfileRepo(self)
        self.vacancies = _VacancyRepo(self)
        self.applications = _ApplicationRepo(self)
        self.jobs = _JobStateRepo(self)
        self.journal = _JournalRepo(self)
        self.linkedin_contacts = _LinkedInContactRepo(self)
        self.linkedin_vacancies = _LinkedInVacancyRepo(self)
        self.report_files = _ReportFileRepo(self)
        self._init_schema()
        if fresh:
            log.info(
                "Initialized empty SQLite database at %s (schema + default profile)",
                self.path,
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    name TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    storage_path TEXT,
                    storage_saved_at REAL,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS vacancies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT NOT NULL,
                    vacancy_id TEXT,
                    url TEXT NOT NULL,
                    title TEXT,
                    description TEXT,
                    query TEXT,
                    serp_url TEXT,
                    category TEXT NOT NULL DEFAULT 'LOW',
                    score INTEGER NOT NULL DEFAULT 0,
                    category_reason TEXT,
                    filter_status TEXT NOT NULL DEFAULT 'pending',
                    apply_status TEXT NOT NULL DEFAULT 'queued',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(profile, url)
                );
                CREATE INDEX IF NOT EXISTS idx_vac_profile ON vacancies(profile);
                CREATE INDEX IF NOT EXISTS idx_vac_cat ON vacancies(category, score);
                CREATE INDEX IF NOT EXISTS idx_vac_vid ON vacancies(profile, vacancy_id);
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT NOT NULL,
                    vacancy_url TEXT NOT NULL,
                    vacancy_id TEXT,
                    title TEXT,
                    category TEXT,
                    status TEXT NOT NULL,
                    attempt INTEGER DEFAULT 1,
                    error TEXT,
                    dry_run INTEGER DEFAULT 0,
                    duration_ms INTEGER,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_app_profile ON applications(profile);
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    profile TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    event TEXT NOT NULL,
                    message TEXT,
                    payload TEXT,
                    service TEXT NOT NULL DEFAULT 'hh'
                );
                CREATE INDEX IF NOT EXISTS idx_journal_ts ON journal(ts);
                CREATE TABLE IF NOT EXISTS job_state (
                    profile TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'idle',
                    message TEXT,
                    stats_json TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS linkedin_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT NOT NULL,
                    url TEXT NOT NULL,
                    name TEXT,
                    headline TEXT,
                    location TEXT,
                    query TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(profile, url)
                );
                CREATE INDEX IF NOT EXISTS idx_li_contacts_profile
                    ON linkedin_contacts(profile);
                CREATE TABLE IF NOT EXISTS linkedin_vacancies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    company TEXT,
                    location TEXT,
                    query TEXT,
                    source TEXT NOT NULL DEFAULT 'linkedin',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(profile, url)
                );
                CREATE INDEX IF NOT EXISTS idx_li_vac_profile
                    ON linkedin_vacancies(profile);
                CREATE TABLE IF NOT EXISTS report_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    scheduled INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_report_files_ts
                    ON report_files(created_at);
                """
            )
            self._migrate_journal_service(c)
        # Bootstrap only when the DB has no profiles at all.
        if not self.profiles.list_profiles():
            self.profiles.ensure_profile("default")

    @staticmethod
    def _migrate_journal_service(c: sqlite3.Connection) -> None:
        cols = {str(r[1]) for r in c.execute("PRAGMA table_info(journal)").fetchall()}
        if "service" not in cols:
            c.execute(
                "ALTER TABLE journal ADD COLUMN service TEXT NOT NULL DEFAULT 'hh'"
            )
            c.execute(
                """
                UPDATE journal SET service='linkedin'
                WHERE lower(event) LIKE 'linkedin_%'
                """
            )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_journal_service
                ON journal(profile, service, ts)
            """
        )

    def stats(self, profile: str) -> dict[str, Any]:
        return self.applications.stats(profile)

    def get_meta(self, key: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
            return str(row["value"]) if row and row["value"] is not None else None

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )


class _ProfileRepo:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def list_profiles(self) -> list[Profile]:
        with self._uow._conn() as c:
            rows = c.execute("SELECT * FROM profiles ORDER BY name").fetchall()
            return [_row_profile(r) for r in rows]

    def ensure_profile(self, name: str) -> Profile:
        name = _clean_profile_name(name, fallback="default")
        with self._uow._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO profiles(name, created_at) VALUES (?, ?)",
                (name, time.time()),
            )
            c.execute(
                "INSERT OR IGNORE INTO job_state(profile, status, message, stats_json, updated_at)"
                " VALUES (?, 'idle', '', '{}', ?)",
                (name, time.time()),
            )
            row = c.execute("SELECT * FROM profiles WHERE name=?", (name,)).fetchone()
            return _row_profile(row)

    def resolve_profile(self, name: str | None = None) -> str:
        """Pick an existing profile; create `default` only if the table is empty."""
        wanted = (name or "").strip()
        existing = self.list_profiles()
        names = [p.name for p in existing]
        if not names:
            return self.ensure_profile(wanted or "default").name
        if wanted and wanted in names:
            return wanted
        return names[0]

    def rename_profile(self, old_name: str, new_name: str) -> Profile:
        old_name = _clean_profile_name(old_name)
        new_name = _clean_profile_name(new_name)
        with self._uow._conn() as c:
            old = c.execute(
                "SELECT * FROM profiles WHERE name=?", (old_name,)
            ).fetchone()
            if not old:
                raise ValueError(f"profile not found: {old_name}")
            if old_name == new_name:
                return _row_profile(old)
            exists = c.execute(
                "SELECT 1 FROM profiles WHERE name=?", (new_name,)
            ).fetchone()
            if exists:
                raise ValueError(f"profile already exists: {new_name}")
            for table in (
                "vacancies",
                "applications",
                "journal",
                "job_state",
                "linkedin_contacts",
                "linkedin_vacancies",
                "report_files",
            ):
                c.execute(
                    f"UPDATE {table} SET profile=? WHERE profile=?",
                    (new_name, old_name),
                )
            c.execute(
                "UPDATE profiles SET name=? WHERE name=?",
                (new_name, old_name),
            )
            row = c.execute(
                "SELECT * FROM profiles WHERE name=?", (new_name,)
            ).fetchone()
            return _row_profile(row)

    def delete_profile(self, name: str) -> str:
        """Delete profile and related rows.

        Recreate empty `default` only when no profiles remain.
        If others exist, do not recreate `default` — return the first remaining name.
        """
        name = _clean_profile_name(name)
        with self._uow._conn() as c:
            row = c.execute(
                "SELECT name FROM profiles WHERE name=?", (name,)
            ).fetchone()
            if not row:
                raise ValueError(f"profile not found: {name}")
            for table in (
                "vacancies",
                "applications",
                "journal",
                "job_state",
                "linkedin_contacts",
                "linkedin_vacancies",
                "report_files",
            ):
                c.execute(f"DELETE FROM {table} WHERE profile=?", (name,))
            c.execute("DELETE FROM profiles WHERE name=?", (name,))
            remaining = c.execute(
                "SELECT name FROM profiles ORDER BY name"
            ).fetchall()
            if not remaining:
                now = time.time()
                c.execute(
                    "INSERT INTO profiles(name, created_at) VALUES (?, ?)",
                    ("default", now),
                )
                c.execute(
                    "INSERT INTO job_state(profile, status, message, stats_json, updated_at)"
                    " VALUES (?, 'idle', '', '{}', ?)",
                    ("default", now),
                )
                return "default"
            return remaining[0]["name"]

    def save_session(self, profile: str, storage_path: Path) -> None:
        with self._uow._conn() as c:
            c.execute(
                "UPDATE profiles SET storage_path=?, storage_saved_at=? WHERE name=?",
                (str(storage_path), time.time(), profile),
            )

    def get_session_path(self, profile: str) -> str | None:
        with self._uow._conn() as c:
            row = c.execute(
                "SELECT storage_path FROM profiles WHERE name=?", (profile,)
            ).fetchone()
            return row["storage_path"] if row and row["storage_path"] else None


class _VacancyRepo:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def upsert(self, vacancy: Vacancy) -> int:
        now = time.time()
        cat = vacancy.category.value if isinstance(vacancy.category, FitCategory) else str(vacancy.category)
        apply = (
            vacancy.apply_status.value
            if isinstance(vacancy.apply_status, ApplyStatus)
            else str(vacancy.apply_status)
        )
        with self._uow._conn() as c:
            c.execute(
                """
                INSERT INTO vacancies(
                    profile, vacancy_id, url, title, description, query, serp_url,
                    category, score, category_reason, filter_status, apply_status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile, url) DO UPDATE SET
                    title=COALESCE(excluded.title, vacancies.title),
                    description=COALESCE(excluded.description, vacancies.description),
                    category=excluded.category,
                    score=excluded.score,
                    category_reason=excluded.category_reason,
                    filter_status=excluded.filter_status,
                    apply_status=CASE
                        WHEN vacancies.apply_status IN ('applied','dry_run') THEN vacancies.apply_status
                        ELSE excluded.apply_status
                    END,
                    updated_at=excluded.updated_at
                """,
                (
                    vacancy.profile,
                    vacancy.vacancy_id,
                    vacancy.url,
                    vacancy.title,
                    vacancy.description,
                    vacancy.query,
                    vacancy.serp_url,
                    cat,
                    int(vacancy.score),
                    vacancy.category_reason,
                    vacancy.filter_status,
                    apply,
                    now,
                    now,
                ),
            )
            row = c.execute(
                "SELECT id FROM vacancies WHERE profile=? AND url=?",
                (vacancy.profile, vacancy.url),
            ).fetchone()
            return int(row["id"])

    def exists(
        self,
        profile: str,
        *,
        url: str | None = None,
        vacancy_id: str | None = None,
    ) -> bool:
        url = (url or "").strip()
        vacancy_id = (vacancy_id or "").strip()
        if not url and not vacancy_id:
            return False
        with self._uow._conn() as c:
            if url and vacancy_id:
                row = c.execute(
                    """
                    SELECT 1 FROM vacancies
                    WHERE profile=? AND (url=? OR vacancy_id=?)
                    LIMIT 1
                    """,
                    (profile, url, vacancy_id),
                ).fetchone()
            elif vacancy_id:
                row = c.execute(
                    """
                    SELECT 1 FROM vacancies
                    WHERE profile=? AND vacancy_id=?
                    LIMIT 1
                    """,
                    (profile, vacancy_id),
                ).fetchone()
            else:
                row = c.execute(
                    """
                    SELECT 1 FROM vacancies
                    WHERE profile=? AND url=?
                    LIMIT 1
                    """,
                    (profile, url),
                ).fetchone()
        return row is not None

    def known_keys(self, profile: str) -> tuple[set[str], set[str]]:
        """Return (urls, vacancy_ids) already stored for profile."""
        with self._uow._conn() as c:
            rows = c.execute(
                "SELECT url, vacancy_id FROM vacancies WHERE profile=?",
                (profile,),
            ).fetchall()
        urls: set[str] = set()
        ids: set[str] = set()
        for r in rows:
            u = (r["url"] or "").strip()
            if u:
                urls.add(u)
            vid = (r["vacancy_id"] or "").strip()
            if vid:
                ids.add(vid)
        return urls, ids

    def list_for_profile(
        self,
        profile: str,
        *,
        apply_status: str | None = None,
        limit: int = 200,
    ) -> list[Vacancy]:
        with self._uow._conn() as c:
            sql = "SELECT * FROM vacancies WHERE profile=?"
            params: list[Any] = [profile]
            if apply_status:
                sql += " AND apply_status=?"
                params.append(apply_status)
            rows = c.execute(sql, params).fetchall()
        items = [_row_vacancy(r) for r in rows]
        items.sort(key=lambda v: (v.category.priority, -v.score, v.id or 0))
        return items[:limit]

    def next_queued(self, profile: str, limit: int = 100) -> list[Vacancy]:
        return [
            v
            for v in self.list_for_profile(profile, apply_status="queued", limit=limit * 2)
            if v.filter_status == "ok"
        ][:limit]

    def set_apply_status(self, vacancy_pk: int, status: str) -> None:
        with self._uow._conn() as c:
            c.execute(
                "UPDATE vacancies SET apply_status=?, updated_at=? WHERE id=?",
                (status, time.time(), vacancy_pk),
            )


class _ApplicationRepo:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def already_applied(self, profile: str, vacancy_url: str) -> bool:
        with self._uow._conn() as c:
            row = c.execute(
                """
                SELECT 1 FROM applications
                WHERE profile=? AND vacancy_url=?
                  AND (status IN ('applied','skipped','dry_run') OR status LIKE 'filtered:%')
                LIMIT 1
                """,
                (profile, vacancy_url),
            ).fetchone()
            return row is not None

    def count_applied_since(self, profile: str, since_ts: float) -> int:
        with self._uow._conn() as c:
            row = c.execute(
                """
                SELECT COUNT(*) AS n FROM applications
                WHERE profile=? AND status='applied' AND dry_run=0 AND created_at>=?
                """,
                (profile, since_ts),
            ).fetchone()
            return int(row["n"])

    def record(self, application: Application) -> None:
        with self._uow._conn() as c:
            c.execute(
                """
                INSERT INTO applications(
                    profile, vacancy_url, vacancy_id, title, category,
                    status, attempt, error, dry_run, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application.profile,
                    application.vacancy_url,
                    application.vacancy_id,
                    application.title,
                    application.category,
                    application.status,
                    application.attempt,
                    application.error,
                    int(application.dry_run),
                    application.duration_ms,
                    time.time(),
                ),
            )

    def stats(self, profile: str) -> dict[str, Any]:
        with self._uow._conn() as c:
            by_cat = {
                r["category"]: r["n"]
                for r in c.execute(
                    """
                    SELECT category, COUNT(*) AS n FROM vacancies
                    WHERE profile=? AND filter_status='ok' GROUP BY category
                    """,
                    (profile,),
                )
            }
            by_apply = {
                r["apply_status"]: r["n"]
                for r in c.execute(
                    """
                    SELECT apply_status, COUNT(*) AS n FROM vacancies
                    WHERE profile=? GROUP BY apply_status
                    """,
                    (profile,),
                )
            }
            by_app = {
                r["status"]: r["n"]
                for r in c.execute(
                    """
                    SELECT status, COUNT(*) AS n FROM applications
                    WHERE profile=? GROUP BY status
                    """,
                    (profile,),
                )
            }
            queued = c.execute(
                """
                SELECT COUNT(*) AS n FROM vacancies
                WHERE profile=? AND apply_status='queued' AND filter_status='ok'
                """,
                (profile,),
            ).fetchone()["n"]
        return {
            "by_category": by_cat,
            "by_apply_status": by_apply,
            "applications": by_app,
            "queued": int(queued),
            "high": int(by_cat.get("HIGH", 0)),
            "medium": int(by_cat.get("MEDIUM", 0)),
            "low": int(by_cat.get("LOW", 0)),
            "applied": int(by_app.get("applied", 0)),
        }


class _JobStateRepo:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def set_status(
        self,
        profile: str,
        status: JobStatus | str,
        message: str = "",
        stats: dict[str, Any] | None = None,
    ) -> None:
        st = status.value if isinstance(status, JobStatus) else str(status)
        with self._uow._conn() as c:
            existing = c.execute(
                "SELECT stats_json FROM job_state WHERE profile=?", (profile,)
            ).fetchone()
            if stats is None and existing:
                stats_json = existing["stats_json"] or "{}"
            else:
                stats_json = json.dumps(stats or {}, ensure_ascii=False)
            c.execute(
                """
                INSERT INTO job_state(profile, status, message, stats_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(profile) DO UPDATE SET
                    status=excluded.status,
                    message=excluded.message,
                    stats_json=excluded.stats_json,
                    updated_at=excluded.updated_at
                """,
                (profile, st, message, stats_json, time.time()),
            )

    def get_status(self, profile: str) -> JobState:
        with self._uow._conn() as c:
            row = c.execute(
                "SELECT * FROM job_state WHERE profile=?", (profile,)
            ).fetchone()
        if not row:
            return JobState(profile=profile)
        try:
            status = JobStatus(row["status"])
        except ValueError:
            status = JobStatus.IDLE
        return JobState(
            profile=row["profile"],
            status=status,
            message=row["message"] or "",
            stats=json.loads(row["stats_json"] or "{}"),
            updated_at=row["updated_at"],
        )


class _JournalRepo:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def log(
        self,
        profile: str,
        event: str,
        message: str = "",
        level: str = "info",
        payload: dict[str, Any] | None = None,
        *,
        service: str | None = None,
    ) -> None:
        svc = normalize_journal_service(service, event=event)
        with self._uow._conn() as c:
            c.execute(
                """
                INSERT INTO journal(ts, profile, level, event, message, payload, service)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    profile,
                    level,
                    event,
                    message,
                    json.dumps(payload or {}, ensure_ascii=False),
                    svc,
                ),
            )

    def recent(
        self,
        profile: str | None = None,
        limit: int = 80,
        *,
        service: str | None = None,
    ) -> list[JournalEntry]:
        svc = normalize_journal_service(service) if service else None
        with self._uow._conn() as c:
            if profile and svc:
                rows = c.execute(
                    """
                    SELECT * FROM journal WHERE profile=? AND service=?
                    ORDER BY ts DESC LIMIT ?
                    """,
                    (profile, svc, limit),
                ).fetchall()
            elif profile:
                rows = c.execute(
                    """
                    SELECT * FROM journal WHERE profile=?
                    ORDER BY ts DESC LIMIT ?
                    """,
                    (profile, limit),
                ).fetchall()
            elif svc:
                rows = c.execute(
                    """
                    SELECT * FROM journal WHERE service=?
                    ORDER BY ts DESC LIMIT ?
                    """,
                    (svc, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM journal ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out: list[JournalEntry] = []
        for r in rows:
            keys = r.keys()
            out.append(
                JournalEntry(
                    id=r["id"],
                    ts=r["ts"],
                    profile=r["profile"],
                    level=r["level"],
                    event=r["event"],
                    message=r["message"] or "",
                    payload=json.loads(r["payload"] or "{}"),
                    service=normalize_journal_service(
                        r["service"] if "service" in keys else None,
                        event=r["event"],
                    ),
                )
            )
        return out


class _LinkedInContactRepo:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def upsert(self, contact: LinkedInContact) -> int:
        now = time.time()
        with self._uow._conn() as c:
            c.execute(
                """
                INSERT INTO linkedin_contacts(
                    profile, url, name, headline, location, query,
                    status, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile, url) DO UPDATE SET
                    name=COALESCE(excluded.name, linkedin_contacts.name),
                    headline=COALESCE(excluded.headline, linkedin_contacts.headline),
                    location=COALESCE(excluded.location, linkedin_contacts.location),
                    query=COALESCE(excluded.query, linkedin_contacts.query),
                    status=excluded.status,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    contact.profile,
                    contact.url,
                    contact.name,
                    contact.headline,
                    contact.location,
                    contact.query,
                    contact.status,
                    contact.error,
                    now,
                    now,
                ),
            )
            row = c.execute(
                "SELECT id FROM linkedin_contacts WHERE profile=? AND url=?",
                (contact.profile, contact.url),
            ).fetchone()
            return int(row["id"])

    def list_for_profile(self, profile: str, limit: int = 200) -> list[LinkedInContact]:
        with self._uow._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM linkedin_contacts WHERE profile=?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (profile, limit),
            ).fetchall()
        return [_row_li_contact(r) for r in rows]

    def stats(self, profile: str) -> dict[str, Any]:
        with self._uow._conn() as c:
            by_status = {
                r["status"]: r["n"]
                for r in c.execute(
                    """
                    SELECT status, COUNT(*) AS n FROM linkedin_contacts
                    WHERE profile=? GROUP BY status
                    """,
                    (profile,),
                )
            }
            total = c.execute(
                "SELECT COUNT(*) AS n FROM linkedin_contacts WHERE profile=?",
                (profile,),
            ).fetchone()["n"]
        return {"by_status": by_status, "total": int(total)}


class _LinkedInVacancyRepo:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def upsert(self, vacancy: LinkedInVacancyLink) -> int:
        now = time.time()
        with self._uow._conn() as c:
            c.execute(
                """
                INSERT INTO linkedin_vacancies(
                    profile, url, title, company, location, query, source,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile, url) DO UPDATE SET
                    title=COALESCE(excluded.title, linkedin_vacancies.title),
                    company=COALESCE(excluded.company, linkedin_vacancies.company),
                    location=COALESCE(excluded.location, linkedin_vacancies.location),
                    query=COALESCE(excluded.query, linkedin_vacancies.query),
                    updated_at=excluded.updated_at
                """,
                (
                    vacancy.profile,
                    vacancy.url,
                    vacancy.title,
                    vacancy.company,
                    vacancy.location,
                    vacancy.query,
                    vacancy.source or "linkedin",
                    now,
                    now,
                ),
            )
            row = c.execute(
                "SELECT id FROM linkedin_vacancies WHERE profile=? AND url=?",
                (vacancy.profile, vacancy.url),
            ).fetchone()
            return int(row["id"])

    def exists(self, profile: str, *, url: str | None = None) -> bool:
        url = (url or "").strip()
        if not url:
            return False
        with self._uow._conn() as c:
            row = c.execute(
                """
                SELECT 1 FROM linkedin_vacancies
                WHERE profile=? AND url=?
                LIMIT 1
                """,
                (profile, url),
            ).fetchone()
        return row is not None

    def known_urls(self, profile: str) -> set[str]:
        with self._uow._conn() as c:
            rows = c.execute(
                "SELECT url FROM linkedin_vacancies WHERE profile=?",
                (profile,),
            ).fetchall()
        return {(r["url"] or "").strip() for r in rows if (r["url"] or "").strip()}

    def list_for_profile(
        self, profile: str, limit: int = 200
    ) -> list[LinkedInVacancyLink]:
        with self._uow._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM linkedin_vacancies WHERE profile=?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (profile, limit),
            ).fetchall()
        return [_row_li_vacancy(r) for r in rows]

    def stats(self, profile: str) -> dict[str, Any]:
        with self._uow._conn() as c:
            total = c.execute(
                "SELECT COUNT(*) AS n FROM linkedin_vacancies WHERE profile=?",
                (profile,),
            ).fetchone()["n"]
        return {"total": int(total)}


class _ReportFileRepo:
    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def record(
        self,
        profile: str,
        kind: str,
        path: str,
        *,
        scheduled: bool = False,
    ) -> int:
        with self._uow._conn() as c:
            cur = c.execute(
                """
                INSERT INTO report_files(profile, kind, path, created_at, scheduled)
                VALUES (?, ?, ?, ?, ?)
                """,
                (profile, kind, path, time.time(), int(scheduled)),
            )
            return int(cur.lastrowid or 0)

    def list_recent(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._uow._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM report_files ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "profile": r["profile"],
                "kind": r["kind"],
                "path": r["path"],
                "created_at": r["created_at"],
                "scheduled": bool(r["scheduled"]),
            }
            for r in rows
        ]

    def last_scheduled(self) -> dict[str, Any] | None:
        with self._uow._conn() as c:
            row = c.execute(
                """
                SELECT * FROM report_files WHERE scheduled=1
                ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "profile": row["profile"],
            "kind": row["kind"],
            "path": row["path"],
            "created_at": row["created_at"],
            "scheduled": True,
        }


def _row_li_contact(r: sqlite3.Row) -> LinkedInContact:
    return LinkedInContact(
        id=r["id"],
        profile=r["profile"],
        url=r["url"],
        name=r["name"] or "",
        headline=r["headline"] or "",
        location=r["location"] or "",
        query=r["query"] or "",
        status=r["status"] or "pending",
        error=r["error"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _row_li_vacancy(r: sqlite3.Row) -> LinkedInVacancyLink:
    return LinkedInVacancyLink(
        id=r["id"],
        profile=r["profile"],
        url=r["url"],
        title=r["title"] or "",
        company=r["company"] or "",
        location=r["location"] or "",
        query=r["query"] or "",
        source=r["source"] or "linkedin",
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _clean_profile_name(name: str, *, fallback: str | None = None) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        if fallback is not None:
            return fallback
        raise ValueError("empty profile name")
    if len(cleaned) > 64:
        raise ValueError("profile name too long")
    if cleaned in (".", "..") or any(ch in cleaned for ch in ("/", "\\", "\0")):
        raise ValueError("invalid profile name")
    return cleaned


def _row_profile(r: sqlite3.Row) -> Profile:
    return Profile(
        name=r["name"],
        storage_path=r["storage_path"],
        storage_saved_at=r["storage_saved_at"],
        notes=r["notes"],
        created_at=r["created_at"],
    )


def _row_vacancy(r: sqlite3.Row) -> Vacancy:
    try:
        cat = FitCategory(r["category"] or "LOW")
    except ValueError:
        cat = FitCategory.LOW
    try:
        apply = ApplyStatus(r["apply_status"] or "queued")
    except ValueError:
        apply = ApplyStatus.QUEUED
    return Vacancy(
        id=r["id"],
        profile=r["profile"],
        vacancy_id=r["vacancy_id"],
        url=r["url"],
        title=r["title"] or "",
        description=r["description"] or "",
        query=r["query"] or "",
        serp_url=r["serp_url"] or "",
        category=cat,
        score=int(r["score"] or 0),
        category_reason=r["category_reason"] or "",
        filter_status=r["filter_status"] or "pending",
        apply_status=apply,
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )
