"""Config soft-defaults, LinkedIn profile, report schedule parsing."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.config_defaults import deep_merge_defaults
from app.domain.launch_profile import (
    HH_LAUNCH_DEFAULTS,
    load_launch_profile_with_notes,
    validate_launch_dict,
)
from app.domain.linkedin_profile import (
    LINKEDIN_LAUNCH_DEFAULTS,
    load_linkedin_launch,
    validate_linkedin_dict,
)
from app.infrastructure.scheduler import next_run_at, resolve_tz
from app.infrastructure.settings import Settings


def test_deep_merge_fills_missing_keys():
    raw = {"connect_limit": 5}
    merged, notes = deep_merge_defaults(raw, LINKEDIN_LAUNCH_DEFAULTS, prefix="linkedin")
    assert merged["connect_limit"] == 5
    assert merged["locations"] == LINKEDIN_LAUNCH_DEFAULTS["locations"]
    assert any("locations" in n for n in notes)


def test_linkedin_load_missing_file_uses_defaults(tmp_path: Path):
    path = tmp_path / "missing.json"
    profile, result = load_linkedin_launch(path)
    assert profile.connect_limit == LINKEDIN_LAUNCH_DEFAULTS["connect_limit"]
    assert result.used_defaults or result.notifications
    assert "Minsk" in profile.locations


def test_linkedin_partial_file(tmp_path: Path):
    path = tmp_path / "li.json"
    path.write_text(
        json.dumps({"connect_limit": 3, "locations": ["Minsk"]}),
        encoding="utf-8",
    )
    profile, result = load_linkedin_launch(path)
    assert profile.connect_limit == 3
    assert profile.locations == ["Minsk"]
    assert profile.people_queries  # default filled
    assert any("people_queries" in n or "vacancy" in n for n in result.notifications)


def test_linkedin_validate_ok():
    p = validate_linkedin_dict(dict(LINKEDIN_LAUNCH_DEFAULTS))
    assert len(p.people_search_combos()) >= 3


def test_hh_launch_soft_defaults_partial(tmp_path: Path):
    path = tmp_path / "launch.json"
    path.write_text(
        json.dumps(
            {
                "site": "hh.ru",
                "location": {"country": "Россия", "city": "Москва"},
                "queries": ["python"],
            }
        ),
        encoding="utf-8",
    )
    profile, notes = load_launch_profile_with_notes(path)
    assert profile is not None
    assert profile.site == "hh.ru"
    assert profile.apply_limit == HH_LAUNCH_DEFAULTS["apply_limit"]
    assert profile.vacancy_limit == HH_LAUNCH_DEFAULTS["vacancy_limit"]
    assert profile.salary_min_usd == 2200
    # optional keys filled → notifications may mention them
    assert isinstance(notes, list)


def test_hh_launch_missing_file_defaults(tmp_path: Path):
    profile, notes = load_launch_profile_with_notes(tmp_path / "nope.json")
    assert profile is not None
    assert profile.site == "rabota.by"
    assert notes


def test_report_schedule_cron_parse():
    s = Settings(
        report_schedule_cron="15 3 * * *",
        report_schedule_hour=4,
        report_schedule_minute=0,
        report_schedule_timezone="Europe/Minsk",
    )
    sched = s.parse_report_schedule()
    assert sched["hour"] == 3
    assert sched["minute"] == 15
    assert sched["timezone"] == "Europe/Minsk"


def test_report_schedule_bad_cron_keeps_hour():
    s = Settings(
        report_schedule_cron="not-a-cron",
        report_schedule_hour=4,
        report_schedule_minute=30,
    )
    sched = s.parse_report_schedule()
    assert sched["hour"] == 4
    assert sched["minute"] == 30
    assert sched["notifications"]


def test_next_run_at_rolls_forward():
    from datetime import datetime

    tz = resolve_tz("Europe/Minsk")
    now = datetime(2026, 8, 6, 5, 0, tzinfo=tz)
    nxt = next_run_at(4, 0, tz, now=now)
    assert nxt.day == 7
    assert nxt.hour == 4


def test_validate_launch_defaults_dict():
    p = validate_launch_dict(dict(HH_LAUNCH_DEFAULTS))
    assert p.search_area == "1002"


def test_default_app_name_and_sqlite_basename(monkeypatch):
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.app_name == "auto-apply-app"
    assert "auto_apply_app.sqlite" in s.database_url
    assert "rabota_apply" not in s.database_url

