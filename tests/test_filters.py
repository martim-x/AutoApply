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
    has_python_title_gate,
    is_gov_related,
    is_remote_or_hybrid,
    looks_office_only,
)
from app.infrastructure.browser.gateway import pick_vacancy_description


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


def test_python_signal_soft_vs_title_gate():
    # Soft: description still counts for scoring bonus / legacy helpers.
    assert has_python_signal("Python-разработчик", "")
    assert has_python_signal("Backend", "Стек: Django, FastAPI")
    assert not has_python_signal("Java developer", "Spring Boot only")

    # Hard title gate: description-only Python must not pass.
    assert has_python_title_gate("Python-разработчик")
    assert has_python_title_gate("Backend Python engineer")
    assert has_python_title_gate("Django developer")
    assert not has_python_title_gate("Backend engineer")
    assert not has_python_title_gate("Java developer")
    assert not has_python_title_gate("Менеджер по продажам")


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


def test_evaluate_filters_sales_even_with_body_python_chrome():
    chrome = (
        "Менеджер по продажам B2B. Удалённо. "
        "Похожие вакансии: Python-разработчик, Django backend, FastAPI engineer."
    )
    r = evaluate_vacancy(
        "https://rabota.by/vacancy/sales",
        "Менеджер по продажам",
        chrome,
        require_remote_or_hybrid=True,
        require_python_keywords=True,
    )
    assert r.ok is False
    assert r.reason == "filtered:no_python"


def test_evaluate_filters_java_without_python_title():
    r = evaluate_vacancy(
        "https://rabota.by/vacancy/java",
        "Java developer",
        "Spring Boot. Nice to have: Python scripts. Remote.",
        require_remote_or_hybrid=True,
        require_python_keywords=True,
    )
    assert r.ok is False
    assert r.reason == "filtered:no_python"


def test_pick_vacancy_description_prefers_block_over_body():
    desc = "Обязанности: разработка API на FastAPI. " * 5
    body = desc + " Похожие вакансии: Python sales Java C# SEO"
    assert pick_vacancy_description([desc], body_fallback=body) == desc.strip()[:80_000]
    # empty/short blocks → fall back to body
    short = pick_vacancy_description(["tiny"], body_fallback="x" * 100)
    assert short.startswith("x")
