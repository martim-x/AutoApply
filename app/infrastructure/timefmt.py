"""Timezone-aware display stamps (journal, PDF labels, report filenames)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)


def resolve_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Europe/Minsk")
    except ZoneInfoNotFoundError:
        log.warning("Unknown timezone %r — falling back to Europe/Minsk", name)
        return ZoneInfo("Europe/Minsk")


def display_timezone_name(settings: Any | None = None) -> str:
    """
    Prefer launch.schedule.timezone, else PARSE/REPORT schedule TZ, else Europe/Minsk.
    """
    if settings is not None:
        try:
            from app.domain.launch_profile import load_launch_profile

            launch = load_launch_profile(settings.launch_path)
            sched = getattr(launch, "schedule", None) if launch else None
            tz = (getattr(sched, "timezone", None) or "").strip()
            if tz:
                return tz
        except Exception:
            pass
        for attr in ("parse_schedule_timezone", "report_schedule_timezone"):
            raw = getattr(settings, attr, None)
            if raw and str(raw).strip():
                return str(raw).strip()
    return "Europe/Minsk"


def format_ts(
    ts: float | None,
    *,
    tz_name: str | None = None,
    settings: Any | None = None,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """Format unix timestamp in the configured display timezone."""
    if not ts:
        return ""
    name = tz_name or display_timezone_name(settings)
    tz = resolve_tz(name)
    return datetime.fromtimestamp(float(ts), tz=tz).strftime(fmt)


def stamp_now(
    *,
    tz_name: str | None = None,
    settings: Any | None = None,
    fmt: str = "%Y%m%d-%H%M%S",
) -> str:
    """Filename-friendly stamp in the configured display timezone."""
    name = tz_name or display_timezone_name(settings)
    tz = resolve_tz(name)
    return datetime.now(tz).strftime(fmt)
