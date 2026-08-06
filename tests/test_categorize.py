"""Fit categorization tests (weight-graph backed)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.categorize import categorize_vacancy, priority_key
from app.domain.enums import FitCategory


def test_high_python_remote_strong_stack():
    r = categorize_vacancy(
        "Python-разработчик",
        "Удалённо. Стек: Django, FastAPI, PostgreSQL, Docker, pytest. "
        "Обязанности: разработка API. Требования: Middle.",
    )
    assert r.category == FitCategory.HIGH
    assert r.score >= 60
    assert r.explanation


def test_medium_partial():
    r = categorize_vacancy(
        "Backend engineer",
        "Python, remote-first team, REST APIs, PostgreSQL",
    )
    assert r.category in (FitCategory.HIGH, FitCategory.MEDIUM)


def test_low_weak():
    r = categorize_vacancy(
        "PHP / Bitrix разработчик",
        "Только офис, WordPress",
    )
    assert r.category == FitCategory.LOW


def test_priority_order():
    assert priority_key(FitCategory.HIGH, 90) < priority_key(FitCategory.MEDIUM, 99)
    assert priority_key(FitCategory.MEDIUM, 50) < priority_key(FitCategory.LOW, 99)
    assert priority_key("HIGH", 80) < priority_key("HIGH", 50)
