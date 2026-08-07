"""Weighted feature-graph scoring + explanation diversity."""

from __future__ import annotations

from app.domain.enums import FitCategory
from app.domain.scoring import score_vacancy
from app.domain.scoring.engine import load_weight_map, reload_weight_map
from app.domain.scoring.explain import explanations_for_seed_variants


def setup_module(_mod=None):
    reload_weight_map()


def test_high_legend_stack_remote():
    r = score_vacancy(
        "Python backend-разработчик Middle+",
        "Удалённо. FastAPI, PostgreSQL, Redis, RabbitMQ, Docker, pytest. "
        "Продуктовая B2B команда, микросервисы. "
        + ("Описание обязанностей и требований. " * 20),
    )
    assert r.category == FitCategory.HIGH
    assert r.total_weight > 0.55
    assert any(c.id == "fastapi_match" for c in r.contributions)
    assert any(c.id == "python_title_role" for c in r.contributions)
    assert any(c.id == "backend_title_role" for c in r.contributions)
    assert r.explanation


def test_high_python_backend_title():
    r = score_vacancy(
        "Python backend developer",
        "Remote. FastAPI, Django, PostgreSQL, Celery, Redis. "
        + ("Требования и обязанности. " * 15),
    )
    assert r.category == FitCategory.HIGH


def test_low_office_and_php():
    r = score_vacancy(
        "PHP Bitrix разработчик",
        "Только офис, WordPress, без удалёнки",
    )
    assert r.category == FitCategory.LOW
    assert any(c.weight < 0 for c in r.contributions)


def test_sales_manager_low_despite_chrome_python():
    r = score_vacancy(
        "Менеджер по продажам",
        "Удалённо. Похожие вакансии: Python-разработчик, FastAPI, Django backend.",
    )
    assert r.category == FitCategory.LOW
    assert any(c.id == "wrong_role_sales" for c in r.contributions)


def test_java_without_python_title_low():
    r = score_vacancy(
        "Java developer",
        "Remote Spring Boot. Nice to have Python. PostgreSQL, Docker.",
    )
    assert r.category == FitCategory.LOW
    assert any(c.id == "wrong_stack_java" for c in r.contributions)


def test_medium_partial_python_hybrid():
    r = score_vacancy(
        "Backend engineer",
        "Python, hybrid format, REST APIs, PostgreSQL",
    )
    assert r.category == FitCategory.MEDIUM
    ids = {c.id for c in r.contributions}
    assert "backend_title_role" in ids
    assert "python_stack" in ids or "postgres_match" in ids


def test_medium_survives_launch_location_bonus():
    """City/salary launch bonuses must not skip MEDIUM into HIGH alone."""
    from app.domain.launch_profile import LaunchProfile, LocationPref

    launch = LaunchProfile(
        site="rabota.by",
        queries=["python"],
        location=LocationPref(country="Беларусь", city="Минск", strict=True),
        salary_min_usd=2200,
        salary_max_usd=2800,
        level="middle+",
    )
    r = score_vacancy(
        "Backend engineer",
        "Python, remote-first team in Minsk. REST APIs, PostgreSQL.",
        launch=launch,
        location=launch.location,
    )
    assert r.category == FitCategory.MEDIUM
    assert any(c.id == "location_city_hit" for c in r.contributions)
    # role honesty: no python-in-title → never HIGH
    assert r.category != FitCategory.HIGH


def test_salary_below_does_not_leave_high():
    from app.domain.launch_profile import LaunchProfile, LocationPref

    launch = LaunchProfile(
        site="rabota.by",
        queries=["python"],
        location=LocationPref(country="Беларусь", city="Минск", strict=False),
        salary_min_usd=2200,
        salary_max_usd=2800,
        level="middle+",
    )
    r = score_vacancy(
        "Python-разработчик",
        "Удалённо FastAPI Django PostgreSQL Redis. Зарплата от 800 USD.",
        launch=launch,
    )
    assert r.category != FitCategory.HIGH
    assert any(c.id == "salary_below" for c in r.contributions)
    assert r.score <= 40


def test_gov_hard_floor():
    r = score_vacancy(
        "Python Developer",
        "Remote FastAPI Django. Работа в государственной структуре .gov.by",
        url="https://example.gov.by/vacancy/1",
    )
    assert r.category == FitCategory.LOW


def test_contributions_transparent():
    r = score_vacancy(
        "Python Developer",
        "Remote, FastAPI, salary от 2500 USD",
    )
    d = r.as_dict()
    assert "contributions" in d
    assert d["top_positive"]
    assert isinstance(d["total_weight"], float)


def test_explain_templates_diverse():
    wmap = load_weight_map()
    templates = wmap.get("explain_templates") or {}
    r = score_vacancy(
        "Python-разработчик",
        "Удалённо FastAPI PostgreSQL Redis",
    )
    variants = explanations_for_seed_variants(r, templates=templates, n=3)
    assert len(variants) >= 2
    assert len(set(variants)) >= 2


def test_weights_file_has_legend_signals():
    wmap = load_weight_map()
    signals = wmap["signals"]
    assert "fastapi_match" in signals
    assert "django_match" in signals
    assert "backend_title_role" in signals
    assert "wrong_role_sales" in signals
    assert "wrong_stack_csharp" in signals
    assert "office_only" in signals
    assert float(signals["python_title_role"]["weight"]) >= 0.9
    assert float(signals["backend_title_role"]["weight"]) >= 0.8
    assert float(signals["wrong_role_sales"]["weight"]) <= -0.9
    assert float(signals["office_only"]["weight"]) < 0
