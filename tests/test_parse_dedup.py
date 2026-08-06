"""Unit tests for vacancy duplicate detection + old-streak early-stop."""

from __future__ import annotations

from app.domain.parse_dedup import (
    canonical_vacancy_url,
    is_duplicate_vacancy,
    next_old_streak,
    remember_vacancy,
    should_stop_old_streak,
)
from app.infrastructure.settings import Settings, parse_schedule_times_list


def test_next_old_streak_new_resets() -> None:
    assert next_old_streak(3, False) == 0
    assert next_old_streak(0, False) == 0


def test_next_old_streak_old_increments() -> None:
    assert next_old_streak(0, True) == 1
    assert next_old_streak(4, True) == 5


def test_should_stop_at_five() -> None:
    streak = 0
    for _ in range(5):
        streak = next_old_streak(streak, True)
    assert should_stop_old_streak(streak, 5)
    assert not should_stop_old_streak(4, 5)


def test_mixed_sequence_resets_and_stops() -> None:
    # new, old, old, new, old×5 → stop
    streak = 0
    events = [
        False,
        True,
        True,
        False,
        True,
        True,
        True,
        True,
        True,
    ]
    stopped = False
    for is_old in events:
        streak = next_old_streak(streak, is_old)
        if should_stop_old_streak(streak, 5):
            stopped = True
            break
    assert stopped
    assert streak == 5


def test_threshold_zero_never_stops() -> None:
    assert not should_stop_old_streak(100, 0)
    assert not should_stop_old_streak(100, -1)


def test_is_duplicate_by_url_and_id() -> None:
    urls = {"https://rabota.by/vacancy/123"}
    ids = {"123"}
    assert is_duplicate_vacancy(
        url="https://rabota.by/vacancy/123?query=1",
        vacancy_id=None,
        known_urls=urls,
        known_ids=ids,
    )
    assert is_duplicate_vacancy(
        url="https://hh.ru/vacancy/999",
        vacancy_id="123",
        known_urls=urls,
        known_ids=ids,
    )
    assert not is_duplicate_vacancy(
        url="https://rabota.by/vacancy/456",
        vacancy_id="456",
        known_urls=urls,
        known_ids=ids,
    )


def test_is_duplicate_linkedin() -> None:
    urls = {"https://www.linkedin.com/jobs/view/987654"}
    ids = {"987654"}
    assert is_duplicate_vacancy(
        url="https://www.linkedin.com/jobs/view/987654/?refId=x",
        vacancy_id=None,
        known_urls=urls,
        known_ids=ids,
    )


def test_remember_vacancy_adds_keys() -> None:
    urls: set[str] = set()
    ids: set[str] = set()
    remember_vacancy(
        url="https://rabota.by/vacancy/42?foo=1",
        vacancy_id=None,
        known_urls=urls,
        known_ids=ids,
    )
    assert "42" in ids
    assert canonical_vacancy_url("https://rabota.by/vacancy/42?foo=1") in urls
    assert is_duplicate_vacancy(
        url="https://rabota.by/vacancy/42",
        vacancy_id="42",
        known_urls=urls,
        known_ids=ids,
    )


def test_parse_schedule_times_defaults() -> None:
    times, notes = parse_schedule_times_list("")
    assert times == [(0, 0), (12, 0)]
    assert notes


def test_parse_schedule_times_list() -> None:
    times, notes = parse_schedule_times_list("12:00,00:00")
    assert times == [(0, 0), (12, 0)]
    assert not notes


def test_parse_parse_schedule_soft_defaults() -> None:
    s = Settings(_env_file=None, parse_schedule_times="nope")
    sched = s.parse_parse_schedule()
    assert sched["times"] == [(0, 0), (12, 0)]
    assert sched["old_streak_stop"] == 5
    assert sched["notifications"]
