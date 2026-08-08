"""Launch schedule, launch-path migration, TZ stamps, bitmask helpers."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.launch_profile import (
    HH_DEFAULT_QUERIES,
    HH_LAUNCH_DEFAULTS,
    parse_and_validate_text,
    validate_launch_dict,
)
from app.infrastructure.scheduler import (
    BIT_HH_APPLY,
    BIT_HH_SEARCH,
    BIT_LI_NETWORK,
    BIT_LI_VACANCIES,
    cron_bit,
    resolve_effective_parse_schedule,
)
from app.infrastructure.settings import Settings
from app.infrastructure.timefmt import format_ts, resolve_tz, stamp_now


def test_default_queries_list():
    assert len(HH_DEFAULT_QUERIES) == 17
    assert "Python разработчик fastapi" in HH_DEFAULT_QUERIES
    assert HH_LAUNCH_DEFAULTS["queries"] == HH_DEFAULT_QUERIES


def test_schedule_in_defaults():
    p = validate_launch_dict(dict(HH_LAUNCH_DEFAULTS))
    assert p.schedule.enabled is True
    assert p.schedule.timezone == "Europe/Minsk"
    assert p.schedule.cron_job_rules == "1111"
    assert p.schedule.email_report_after_run is True
    assert "00:00" in p.schedule.times


def test_schedule_dsl_roundtrip():
    text = """
site: rabota.by
country: Беларусь
city: Минск
queries: Python developer
schedule_enabled: true
schedule_timezone: Europe/Minsk
schedule_times: 01:30, 13:00
cron_job_rules: 1010
email_report_after_run: false
"""
    p = parse_and_validate_text(text)
    assert p.schedule.timezone == "Europe/Minsk"
    assert p.schedule.times == ["01:30", "13:00"]
    assert p.schedule.cron_job_rules == "1010"
    assert p.schedule.email_report_after_run is False
    assert p.schedule.job_enabled(0) is True
    assert p.schedule.job_enabled(1) is False


def test_cron_bit_helpers():
    assert cron_bit("1111", BIT_HH_SEARCH)
    assert cron_bit("1111", BIT_HH_APPLY)
    assert cron_bit("1010", BIT_HH_SEARCH)
    assert not cron_bit("1010", BIT_HH_APPLY)
    assert cron_bit("1010", BIT_LI_VACANCIES)
    assert not cron_bit("1010", BIT_LI_NETWORK)


def test_migrate_launch_configs(tmp_path: Path, monkeypatch):
    root_cfg = tmp_path / "config"
    root_cfg.mkdir()
    legacy = root_cfg / "launch.json"
    legacy.write_text(
        json.dumps(
            {
                "site": "rabota.by",
                "location": {"country": "Беларусь", "city": "Минск"},
                "queries": ["Python developer"],
            }
        ),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    new_path = data / "config" / "launch.json"
    monkeypatch.setattr("app.infrastructure.settings.ROOT", tmp_path)
    s = Settings(
        _env_file=None,
        data_dir=data,
        launch_path=new_path,
        linkedin_launch_path=data / "config" / "linkedin.launch.json",
    )
    notes = s.migrate_launch_configs()
    assert new_path.exists()
    assert any("migrated" in n for n in notes)
    # second run is a no-op
    assert s.migrate_launch_configs() == []


def test_format_ts_minsk():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ts = datetime(2026, 8, 8, 15, 0, tzinfo=ZoneInfo("Europe/Minsk")).timestamp()
    label = format_ts(ts, tz_name="Europe/Minsk", fmt="%Y-%m-%d %H:%M")
    assert label == "2026-08-08 15:00"
    stamp = stamp_now(tz_name="Europe/Minsk")
    assert len(stamp) >= 15
    assert resolve_tz("Not/AZone").key == "Europe/Minsk"


def test_effective_schedule_kill_switch(tmp_path: Path):
    path = tmp_path / "launch.json"
    path.write_text(
        json.dumps(
            {
                "site": "rabota.by",
                "location": {"country": "Беларусь", "city": "Минск"},
                "queries": ["Python developer"],
                "schedule": {
                    "enabled": True,
                    "timezone": "Europe/Minsk",
                    "times": ["00:00", "12:00"],
                    "cron_job_rules": "1111",
                    "email_report_after_run": True,
                },
            }
        ),
        encoding="utf-8",
    )
    s = Settings(
        _env_file=None,
        launch_path=path,
        parse_schedule_enabled=False,
    )
    sched = resolve_effective_parse_schedule(s)
    assert sched["enabled"] is False
    assert sched["cron_job_rules"] == "1111"
    assert sched["hh_search"] is True
    assert sched["hh_apply"] is True

    s2 = Settings(
        _env_file=None,
        launch_path=path,
        parse_schedule_enabled=True,
    )
    sched2 = resolve_effective_parse_schedule(s2)
    assert sched2["enabled"] is True
    assert sched2["times_display"] == "00:00,12:00"
