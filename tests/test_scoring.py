"""Weighted feature-graph scoring + explanation diversity."""

from __future__ import annotations

from app.domain.enums import FitCategory
from app.domain.scoring import score_vacancy
from app.domain.scoring.engine import load_weight_map
from app.domain.scoring.explain import explanations_for_seed_variants


def test_high_legend_stack_remote():
    r = score_vacancy(
        "Python-разработчик Middle+",
        "Удалённо. FastAPI, PostgreSQL, Redis, RabbitMQ, Docker, pytest. "
        "Продуктовая B2B команда, микросервисы. "
        + ("Описание обязанностей и требований. " * 20),
    )
    assert r.category == FitCategory.HIGH
    assert r.total_weight > 0.55
    assert any(c.id == "fastapi_match" for c in r.contributions)
    assert r.explanation


def test_low_office_and_php():
    r = score_vacancy(
        "PHP Bitrix разработчик",
        "Только офис, WordPress, без удалёнки",
    )
    assert r.category == FitCategory.LOW
    assert any(c.weight < 0 for c in r.contributions)


def test_medium_partial_python_hybrid():
    r = score_vacancy(
        "Backend engineer",
        "Python, hybrid format, REST APIs, PostgreSQL",
    )
    assert r.category in (FitCategory.HIGH, FitCategory.MEDIUM)
    ids = {c.id for c in r.contributions}
    assert "python_stack" in ids or "postgres_match" in ids


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
    assert "office_only" in signals
    assert float(signals["fastapi_match"]["weight"]) > 0
    assert float(signals["office_only"]["weight"]) < 0
