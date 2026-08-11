"""Конфигурация из .env / окружения (pydantic-settings)."""

from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)

# Default queries (comma-separated) — keep in sync with HH_LAUNCH_DEFAULTS.
_DEFAULT_SEARCH_QUERIES = (
    "Python разработчик,Python разработчик backend,Python разработчик fastapi,"
    "Python разработчик django,Python разработчик middle,Python разработчик developer,"
    "Backend python,Backend python developer,Backend python django,"
    "Backend python разработчик,Backend python fastapi,"
    "Python developer,Python developer fastapi,Python developer middle,"
    "Python developer backend,Python developer django,Python develop"
)


class Settings(BaseSettings):
    """
    Секреты и настройки — только из env / .env.
    Env-имена = UPPER_SNAKE поля (DATABASE_URL, DATA_DIR, …).

    DATABASE_URL:
      - sqlite:///./data/auto_apply_app.sqlite  (default)
      - postgresql+psycopg://user:pass@host:5432/auto_apply_app  (future)

    Missing SQLite file → created empty with schema on startup.
    Legacy: if auto_apply_app.sqlite is missing but rabota_apply.sqlite
    exists in the same directory, it is renamed on startup.
    RESET_DB=true → delete existing SQLite once (then turn off).
    """

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "auto-apply-app"
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # DB — sqlite by default; Postgres via DATABASE_URL (Railway plugin etc.)
    database_url: str = Field(
        default=f"sqlite:///{ROOT / 'data' / 'auto_apply_app.sqlite'}",
    )
    # Wipe once on startup, then set false (destroys data: SQLite file or PG schema).
    reset_db: bool = False
    data_dir: Path = Field(default=ROOT / "data")
    sessions_dir: Path | None = Field(default=None)
    # File or directory of *.txt templates (see LETTER_STYLE).
    letter_path: Path = Field(default=ROOT / "letters")
    # rotate | impact | responsibility | project | filename stem
    letter_style: str = "rotate"
    # Persist under DATA_DIR so Railway volume (/app/data) keeps UI saves.
    # docker-compose may still point at /app/config via LAUNCH_PATH.
    launch_path: Path = Field(default=ROOT / "data" / "config" / "launch.json")
    linkedin_launch_path: Path = Field(
        default=ROOT / "data" / "config" / "linkedin.launch.json"
    )

    # Site / search (defaults; override via launch.json)
    base_url: str = "https://rabota.by"
    search_area: str = "16"  # BY / Minsk country fallback
    search_queries: str = _DEFAULT_SEARCH_QUERIES
    apply_limit: int = 30
    vacancy_limit: int = 30
    dry_run: bool = False
    headless: bool = False

    # Browser fingerprint hardening (anti-bot)
    # Empty user_agent keeps Playwright default; set a real Chrome UA to mask.
    browser_user_agent: str = ""
    browser_timezone: str = "Europe/Minsk"

    # Remote interactive browser (CDP screencast → Web UI)
    # For Railway/Docker: ENABLE_REMOTE_BROWSER=true and HEADLESS=true
    enable_remote_browser: bool = False
    remote_browser_jpeg_quality: int = 55
    remote_browser_every_nth_frame: int = 1

    # Filters
    require_remote_or_hybrid: bool = True
    skip_gov: bool = True
    require_python_keywords: bool = True

    # Rate limits / retry
    min_action_interval: float = 2.0
    after_apply_delay: float = 8.0
    jitter: float = 0.35
    max_per_hour: int = 40
    max_per_day: int = 180
    load_retries: int = 3
    load_retry_delay: float = 2.5
    apply_retries: int = 2
    navigation_timeout_ms: int = 45_000
    content_timeout_ms: int = 20_000
    settle_ms: int = 1200

    # Optional future secrets
    api_key: str | None = None
    db_password: str | None = None

    # Admin UI for editing .env (disabled unless user+password set)
    admin_user: str | None = None
    admin_password: str | None = None
    admin_secret: str | None = None

    # Owner gate (/login) — GATE_* preferred, else ADMIN_*
    # When credentials are set, HTML + /api/* require auth cookies.
    gate_user: str | None = None
    gate_password: str | None = None
    # Set true behind HTTPS (Railway/Fly) so cookies get Secure flag
    auth_cookie_secure: bool = False

    # Scheduled PDF reports (in-process; one Railway service)
    report_schedule_enabled: bool = False
    report_schedule_timezone: str = "Europe/Minsk"
    report_schedule_hour: int = 4
    report_schedule_minute: int = 0
    # Optional cron "m h * * *" — if set, overrides hour/minute
    report_schedule_cron: str | None = None
    report_schedule_kind: str = "work"
    report_schedule_profile: str = "default"

    # Scheduled vacancy parsing (noon + midnight by default; separate from PDF)
    # Off locally for safety; enable on Railway when sessions exist.
    parse_schedule_enabled: bool = False
    parse_schedule_timezone: str = "Europe/Minsk"
    # Comma-separated HH:MM (or bare hours): "12:00,00:00"
    parse_schedule_times: str = "12:00,00:00"
    # Browser cookie profile(s) for cron. "all" / "*" / empty → every profile
    # that has an HH and/or LinkedIn session file; otherwise a single name.
    parse_schedule_profile: str = "all"
    # SERP walk (newest-first): paginate past known listings instead of
    # aborting on a short item streak. Early-stop = consecutive fully-duplicate pages.
    parse_early_stop_enabled: bool = True
    # Optional item-level streak (0 = off). Prefer PARSE_DUP_PAGE_STOP.
    parse_old_streak_stop: int = 0
    # Max SERP pages per query (HH page=0..N-1; LinkedIn start+=25).
    parse_max_serp_pages: int = 20
    # Stop current query after N consecutive pages with only known vacancies.
    parse_dup_page_stop: int = 3

    # SMTP alerts (sync smtplib; short timeouts — one Railway process)
    alert_smtp_enabled: bool = False
    alert_smtp_host: str = ""
    alert_smtp_port: int = 587
    alert_smtp_user: str = ""
    alert_smtp_password: str = ""
    alert_smtp_from: str = ""
    alert_smtp_to: str = ""
    alert_smtp_tls: bool = True
    alert_on_error: bool = True
    alert_on_captcha: bool = True
    alert_on_parse_fail: bool = True
    # Max 1 identical (profile+event+message) email per window
    alert_rate_limit_seconds: int = 600

    @field_validator(
        "alert_smtp_host",
        "alert_smtp_user",
        "alert_smtp_password",
        "alert_smtp_from",
        "alert_smtp_to",
        mode="before",
    )
    @classmethod
    def _strip_smtp_quotes(cls, v: Any) -> Any:
        if v is None:
            return v
        s = str(v).strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            return s[1:-1].strip()
        return s

    @field_validator("alert_smtp_port", mode="before")
    @classmethod
    def _parse_smtp_port(cls, v: Any) -> Any:
        if v is None or v == "":
            return 587
        if isinstance(v, int):
            return v
        s = str(v).strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return int(s) if s else 587

    @field_validator("alert_smtp_enabled", "alert_smtp_tls", mode="before")
    @classmethod
    def _parse_smtp_bool(cls, v: Any) -> Any:
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        s = str(v).strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        low = s.lower()
        if low in {"1", "true", "yes", "on"}:
            return True
        if low in {"0", "false", "no", "off", ""}:
            return False
        return v

    def effective_headless(self) -> bool:
        """
        Chromium launch mode for all browsers (login/search/apply/remote).

        Remote screencast is headless-friendly; when ENABLE_REMOTE_BROWSER is on
        (Docker/Railway), force headless even if HEADLESS=false in local .env —
        headed mode needs an X server that containers typically lack.
        """
        return bool(self.headless or self.enable_remote_browser)

    def admin_enabled(self) -> bool:
        user = (self.admin_user or "").strip()
        password = self.admin_password or ""
        return bool(user and password)

    def gate_credentials(self) -> tuple[str, str] | None:
        """Owner login: GATE_USER/PASSWORD, else ADMIN_USER/PASSWORD."""
        user = (self.gate_user or self.admin_user or "").strip()
        password = self.gate_password or self.admin_password or ""
        if user and password:
            return user, password
        return None

    def gate_enabled(self) -> bool:
        return self.gate_credentials() is not None

    def session_secret(self) -> str:
        """Secret for signed admin cookies; prefer ADMIN_SECRET."""
        if self.admin_secret and self.admin_secret.strip():
            return self.admin_secret.strip()
        # Deterministic fallback so sessions survive restart when secret unset
        # (still requires credentials; not for public multi-tenant use).
        creds = self.gate_credentials()
        if creds:
            user, password = creds
        else:
            user = (self.admin_user or "").strip()
            password = self.admin_password or ""
        return f"auto-apply-app-admin:{user}:{password}"

    def auth_secret(self) -> str:
        """HMAC secret for access/refresh JWTs (nexus_token / refresh_token)."""
        return self.session_secret()

    @field_validator(
        "data_dir",
        "letter_path",
        "launch_path",
        "linkedin_launch_path",
        mode="before",
    )
    @classmethod
    def _as_path(cls, v: Any) -> Path:
        return Path(v) if not isinstance(v, Path) else v

    @property
    def resolved_sessions_dir(self) -> Path:
        return self.sessions_dir or (self.data_dir / "sessions")

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def config_dir(self) -> Path:
        """Writable launch configs on the data volume (areas/weights stay in image)."""
        return self.data_dir / "config"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_sessions_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.migrate_launch_configs()

    def migrate_launch_configs(self) -> list[str]:
        """
        Copy legacy ROOT/config/*.launch.json → DATA_DIR/config/ when the
        new path is missing or empty (Railway redeploy safety).
        """
        notes: list[str] = []
        legacy = ROOT / "config"
        pairs = (
            (legacy / "launch.json", self.launch_path),
            (legacy / "linkedin.launch.json", self.linkedin_launch_path),
        )
        for old, new in pairs:
            try:
                if new.exists() and new.stat().st_size > 0:
                    continue
                if not old.is_file() or old.stat().st_size == 0:
                    continue
                # Do not overwrite an explicit path that already has content.
                if new.exists() and new.resolve() == old.resolve():
                    continue
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, new)
                msg = f"migrated launch config {old} → {new}"
                notes.append(msg)
                log.info(msg)
            except OSError as e:
                log.warning("launch config migration failed %s → %s: %s", old, new, e)
        return notes

    def sqlite_path(self) -> Path | None:
        url = self.database_url
        if url.startswith("sqlite:///"):
            raw = url.removeprefix("sqlite:///")
            p = Path(raw)
            if not p.is_absolute():
                p = ROOT / p
            return p
        return None

    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite:")

    def is_postgres(self) -> bool:
        u = self.database_url.lower()
        return u.startswith("postgres://") or u.startswith("postgresql:")

    def postgres_url(self) -> str:
        """SQLAlchemy URL with psycopg driver; applies DB_PASSWORD if set."""
        from app.infrastructure.db.postgres_uow import normalize_postgres_url

        url = normalize_postgres_url(self.database_url)
        if self.db_password:
            # Inject password when URL has empty or placeholder password
            # postgresql+psycopg://user@host/db  or  …://user:CHANGE_ME@host/db
            try:
                from sqlalchemy.engine.url import make_url

                parsed = make_url(url)
                pwd = parsed.password
                if not pwd or pwd in {"CHANGE_ME", "changeme", "password"}:
                    parsed = parsed.set(password=self.db_password)
                    url = parsed.render_as_string(hide_password=False)
            except Exception:
                pass
        return url

    def search_list(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for part in self.search_queries.replace("\n", ",").split(","):
            q = part.strip()
            if not q:
                continue
            key = q.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(q)
        return out or ["python разработчик"]

    def state_path(self, profile: str) -> Path:
        self.ensure_dirs()
        return self.resolved_sessions_dir / f"{profile}.storage.json"

    def linkedin_state_path(self, profile: str) -> Path:
        """Separate storage_state for LinkedIn (does not overwrite HH session)."""
        self.ensure_dirs()
        return self.resolved_sessions_dir / f"{profile}.linkedin.storage.json"

    def parse_report_schedule(self) -> dict[str, Any]:
        """
        Resolve schedule to hour/minute (+ timezone).
        Supports REPORT_SCHEDULE_CRON as 'm h * * *' (minute hour only).
        """
        hour = int(self.report_schedule_hour)
        minute = int(self.report_schedule_minute)
        cron = (self.report_schedule_cron or "").strip()
        notes: list[str] = []
        if cron:
            parts = cron.split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                minute = int(parts[0])
                hour = int(parts[1])
            else:
                notes.append(
                    f"using default hour/minute because REPORT_SCHEDULE_CRON "
                    f"unparsed: {cron!r}"
                )
        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        return {
            "enabled": bool(self.report_schedule_enabled),
            "timezone": self.report_schedule_timezone or "Europe/Minsk",
            "hour": hour,
            "minute": minute,
            "cron": cron or None,
            "kind": (self.report_schedule_kind or "work").strip().lower() or "work",
            "profile": (self.report_schedule_profile or "default").strip() or "default",
            "notifications": notes,
        }

    def serp_walk_knobs(self) -> dict[str, Any]:
        """
        Shared HH + LinkedIn SERP pagination / early-stop knobs.
        Soft-defaults invalid values; 0 disables the matching stop.
        """
        notes: list[str] = []
        early = bool(self.parse_early_stop_enabled)
        streak = int(self.parse_old_streak_stop)
        if streak < 0:
            notes.append(
                f"using PARSE_OLD_STREAK_STOP=0 because invalid ({streak})"
            )
            streak = 0
        max_pages = int(self.parse_max_serp_pages)
        if max_pages < 1:
            notes.append(
                f"using default PARSE_MAX_SERP_PAGES=20 because invalid ({max_pages})"
            )
            max_pages = 20
        dup_pages = int(self.parse_dup_page_stop)
        if dup_pages < 0:
            notes.append(
                f"using default PARSE_DUP_PAGE_STOP=3 because invalid ({dup_pages})"
            )
            dup_pages = 3
        return {
            "early_stop_enabled": early,
            # Item streak optional; off unless explicitly > 0
            "old_streak_stop": streak if early else 0,
            "max_serp_pages": max_pages,
            # Page-based stop; off when early-stop master switch is false
            "dup_page_stop": dup_pages if early else 0,
            "notifications": notes,
        }

    def parse_parse_schedule(self) -> dict[str, Any]:
        """
        Resolve vacancy-parse schedule (multi-fire times + SERP walk knobs).
        Soft-defaults missing/invalid PARSE_SCHEDULE_TIMES → 12:00,00:00.
        """
        notes: list[str] = []
        times, time_notes = parse_schedule_times_list(self.parse_schedule_times)
        notes.extend(time_notes)
        walk = self.serp_walk_knobs()
        notes.extend(walk.get("notifications") or [])
        tz = (self.parse_schedule_timezone or "").strip() or "Europe/Minsk"
        if not (self.parse_schedule_timezone or "").strip():
            notes.append(
                "using default PARSE_SCHEDULE_TIMEZONE=Europe/Minsk because missing"
            )
        profile = normalize_parse_schedule_profile(self.parse_schedule_profile)
        return {
            "enabled": bool(self.parse_schedule_enabled),
            "timezone": tz,
            "times": times,
            "times_display": ",".join(f"{h:02d}:{m:02d}" for h, m in times),
            "profile": profile,
            "early_stop_enabled": walk["early_stop_enabled"],
            "old_streak_stop": walk["old_streak_stop"],
            "max_serp_pages": walk["max_serp_pages"],
            "dup_page_stop": walk["dup_page_stop"],
            # Prefer both HH + LinkedIn when sessions exist (documented choice)
            "workspaces": ["hh", "linkedin"],
            "notifications": notes,
        }

    def parse_alert_config(self) -> dict[str, Any]:
        """
        Resolve SMTP alert knobs with soft-default notifications when
        enabled but incomplete (host/to missing).
        """
        notes: list[str] = []
        enabled = bool(self.alert_smtp_enabled)
        host = (self.alert_smtp_host or "").strip()
        mail_to = (self.alert_smtp_to or "").strip()
        mail_from = (self.alert_smtp_from or "").strip()
        user = (self.alert_smtp_user or "").strip()
        port = int(self.alert_smtp_port or 587)
        if port < 1 or port > 65535:
            notes.append(
                f"using default ALERT_SMTP_PORT=587 because invalid ({port})"
            )
            port = 587
        window = int(self.alert_rate_limit_seconds or 600)
        if window < 0:
            notes.append(
                "using default ALERT_RATE_LIMIT_SECONDS=600 because invalid"
            )
            window = 600
        if enabled and not host:
            notes.append(
                "ALERT_SMTP_ENABLED but ALERT_SMTP_HOST empty — alerts skipped"
            )
        if enabled and not mail_to:
            notes.append(
                "ALERT_SMTP_ENABLED but ALERT_SMTP_TO empty — alerts skipped"
            )
        if enabled and not mail_from and not user:
            notes.append(
                "ALERT_SMTP_FROM empty — will fall back to ALERT_SMTP_USER/TO"
            )
        return {
            "enabled": enabled,
            "host": host,
            "port": port,
            "user": user,
            "from": mail_from or user or mail_to,
            "to": mail_to,
            "tls": bool(self.alert_smtp_tls),
            "on_error": bool(self.alert_on_error),
            "on_captcha": bool(self.alert_on_captcha),
            "on_parse_fail": bool(self.alert_on_parse_fail),
            "rate_limit_seconds": window,
            "notifications": notes,
        }


def normalize_parse_schedule_profile(raw: str | None) -> str:
    """
    Resolve PARSE_SCHEDULE_PROFILE.

    - empty / "all" / "*" → sentinel "all" (every profile with sessions)
    - otherwise → trimmed profile name
    """
    text = (raw or "").strip()
    if not text or text.casefold() in ("all", "*"):
        return "all"
    return text


def parse_schedule_times_list(
    raw: str | None,
) -> tuple[list[tuple[int, int]], list[str]]:
    """Parse '12:00,00:00' or '12,0' into sorted unique (hour, minute) list."""
    notes: list[str] = []
    default = [(0, 0), (12, 0)]
    text = (raw or "").strip()
    if not text:
        notes.append(
            "using default PARSE_SCHEDULE_TIMES=12:00,00:00 because missing"
        )
        return default, notes

    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for part in text.replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            if ":" in token:
                hs, ms = token.split(":", 1)
                hour = int(hs.strip())
                minute = int(ms.strip())
            else:
                hour = int(token)
                minute = 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("out of range")
        except ValueError:
            notes.append(f"skipping invalid PARSE_SCHEDULE_TIMES token {token!r}")
            continue
        key = (hour, minute)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)

    if not out:
        notes.append(
            "using default PARSE_SCHEDULE_TIMES=12:00,00:00 because invalid"
        )
        return default, notes

    out.sort(key=lambda t: (t[0], t[1]))
    return out, notes


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
