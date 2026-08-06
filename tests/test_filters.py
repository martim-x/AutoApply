"""Domain filter tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.filters import (
    evaluate_vacancy,
    has_python_signal,
    is_gov_related,
    is_remote_or_hybrid,
    looks_office_only,
)


def test_gov_detection():
    assert is_gov_related("https://jobs.company.gov.by/vacancy/1")
    assert is_gov_related("", "Пишите на hr@ministry.gov.ru")
    assert not is_gov_related("https://rabota.by/vacancy/1", "IT компания")


def test_remote_hybrid():
    assert is_remote_or_hybrid("Python", "Формат: удалённо")
    assert is_remote_or_hybrid("", "hybrid / 2+3")
    assert not is_remote_or_hybrid("Python", "Офис в центре Минска")


def test_office_only():
    assert looks_office_only("", "Работа только в офисе, без удалёнки")


def test_python_signal():
    assert has_python_signal("Python-разработчик", "")
    assert has_python_signal("Backend", "Стек: Django, FastAPI")
    assert not has_python_signal("Java developer", "Spring Boot only")


def test_evaluate_skips_gov():
    r = evaluate_vacancy(
        "https://x.gov.by/job/1",
        "Python remote",
        "Полностью удалённо",
        require_remote_or_hybrid=True,
        skip_gov=True,
    )
    assert r.ok is False
    assert r.reason == "filtered:gov"


def test_evaluate_requires_remote():
    r = evaluate_vacancy(
        "https://rabota.by/vacancy/1",
        "Python developer",
        "Офис в Москве",
        require_remote_or_hybrid=True,
        require_python_keywords=True,
    )
    assert r.ok is False
    assert r.reason == "filtered:office"


def test_evaluate_passes_remote_python():
    r = evaluate_vacancy(
        "https://rabota.by/vacancy/2",
        "Python-разработчик",
        "Формат: удалённый. Django.",
        require_remote_or_hybrid=True,
        require_python_keywords=True,
    )
    assert r.ok is True
