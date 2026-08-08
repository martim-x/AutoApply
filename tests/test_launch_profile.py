"""Tests for launch profile parsing / validation / location scoring."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.filters import evaluate_vacancy
from app.domain.launch_profile import (
    extract_salary_usd,
    launch_to_strict_text,
    level_match_score,
    location_match_score,
    parse_and_validate_text,
    parse_strict_text,
    salary_match_score,
    validate_launch_dict,
)
from app.domain.scoring import score_vacancy

SAMPLE = """
site: rabota.by
country: Беларусь
city: Минск
strict: true
queries: python-разработчик, python-developer
remote_or_hybrid: true
skip_gov: true
python_keywords: true
vacancy_limit: 40
apply_limit: 25
dry_run: true
salary_min_usd: 2200
salary_max_usd: 2800
salary_strict: false
level: middle+
"""


def test_parse_strict_text_ok():
    raw = parse_strict_text(SAMPLE)
    assert raw["site"] == "rabota.by"
    assert raw["location"]["city"] == "Минск"
    profile = validate_launch_dict(raw)
    assert profile.search_area == "1002"
    assert profile.base_url == "https://rabota.by"
    assert profile.dry_run is True
    assert len(profile.queries) == 2
    assert profile.vacancy_limit == 40
    assert profile.apply_limit == 25
    assert profile.salary_min_usd == 2200
    assert profile.salary_max_usd == 2800
    assert profile.level == "middle+"


def test_hh_ru_moscow():
    text = """
site: hh.ru
country: Россия
city: Москва
queries: python developer
"""
    p = parse_and_validate_text(text)
    assert p.site == "hh.ru"
    assert p.search_area == "1"
    assert p.base_url == "https://hh.ru"


def test_site_country_mismatch():
    text = """
site: rabota.by
country: Россия
city: Москва
queries: python
"""
    with pytest.raises((ValueError, ValidationError)):
        parse_and_validate_text(text)


def test_unknown_city():
    text = """
site: rabota.by
country: Беларусь
city: Атлантида
queries: python
"""
    with pytest.raises((ValueError, ValidationError)):
        parse_and_validate_text(text)


def test_unknown_key():
    with pytest.raises(ValueError, match="неизвестный ключ"):
        parse_strict_text("site: rabota.by\nfoo: bar\ncountry: Беларусь\ncity: Минск\nqueries: x")


def test_roundtrip_text():
    p = parse_and_validate_text(SAMPLE)
    again = parse_and_validate_text(launch_to_strict_text(p))
    assert again.site == p.site
    assert again.location.city == p.location.city
    assert again.queries == p.queries
    assert again.vacancy_limit == p.vacancy_limit
    assert again.apply_limit == p.apply_limit


def test_legacy_apply_limit_becomes_vacancy_limit(tmp_path):
    """Old launch.json without vacancy_limit: search cap mirrors apply_limit."""
    from app.domain.launch_profile import load_launch_profile_with_notes

    path = tmp_path / "launch.json"
    path.write_text(
        '{"site":"rabota.by","location":{"country":"Беларусь","city":"Минск"},'
        '"queries":["python"],"apply_limit":17}',
        encoding="utf-8",
    )
    profile, notes = load_launch_profile_with_notes(path)
    assert profile is not None
    assert profile.apply_limit == 17
    assert profile.vacancy_limit == 17
    assert any("vacancy_limit" in n for n in notes)


def test_vacancy_apply_limits_accept_high_ceiling():
    text = SAMPLE.replace("vacancy_limit: 40", "vacancy_limit: 100000").replace(
        "apply_limit: 25", "apply_limit: 100000"
    )
    p = parse_and_validate_text(text)
    assert p.vacancy_limit == 100_000
    assert p.apply_limit == 100_000


def test_vacancy_apply_limits_reject_above_ceiling():
    text = SAMPLE.replace("vacancy_limit: 40", "vacancy_limit: 100001")
    with pytest.raises((ValueError, ValidationError)):
        parse_and_validate_text(text)


def test_strict_false_uses_country_area():
    """Country-wide SERP: strict false → Belarus area=16, not city 1002."""
    text = SAMPLE.replace("strict: true", "strict: false")
    p = parse_and_validate_text(text)
    assert p.search_area == "16"
    assert p.location.country_area_id == "16"


def test_location_filter_other_city():
    p = parse_and_validate_text(SAMPLE)
    r = evaluate_vacancy(
        "https://rabota.by/vacancy/1",
        "Python developer",
        "Полностью удалённая работа. Кандидат из Гомеля предпочтителен. FastAPI.",
        require_remote_or_hybrid=True,
        skip_gov=True,
        require_python_keywords=True,
        location=p.location,
    )
    assert not r.ok
    assert r.status == "filtered:location"


def test_location_score_hit():
    p = parse_and_validate_text(SAMPLE)
    code, w = location_match_score(
        "Python developer в Минске",
        "Удалённая работа, FastAPI",
        p.location,
    )
    assert code == "location_city_hit"
    assert w > 0
    scored = score_vacancy(
        "Python разработчик",
        "Удалёнка FastAPI Django PostgreSQL Минск",
        url="https://rabota.by/vacancy/1",
        location=p.location,
        launch=p,
    )
    assert any(c.id == "location_city_hit" for c in scored.contributions)


def test_salary_in_range_and_below():
    p = parse_and_validate_text(SAMPLE)
    lo, hi = extract_salary_usd("Зарплата 2500–2700 USD remote")
    assert lo == 2500 and hi == 2700
    code, w = salary_match_score(
        "Python",
        "от 2500 до 2700 USD, удалёнка",
        salary_min_usd=p.salary_min_usd,
        salary_max_usd=p.salary_max_usd,
    )
    assert code == "salary_in_range"
    assert w > 0
    code2, w2 = salary_match_score(
        "Python",
        "ЗП 800–1200 USD",
        salary_min_usd=p.salary_min_usd,
        salary_max_usd=p.salary_max_usd,
    )
    assert code2 == "salary_below"
    assert w2 < 0


def test_salary_strict_filter():
    text = SAMPLE.replace("salary_strict: false", "salary_strict: true")
    p = parse_and_validate_text(text)
    r = evaluate_vacancy(
        "https://rabota.by/vacancy/2",
        "Middle Python",
        "Удалённая работа. Зарплата 900–1100 USD. FastAPI.",
        require_remote_or_hybrid=True,
        skip_gov=True,
        require_python_keywords=True,
        launch=p,
    )
    assert not r.ok
    assert r.status == "filtered:salary"


def test_level_signals():
    code, w = level_match_score(
        "Middle+ Python developer",
        "Удалёнка FastAPI",
        "middle+",
    )
    assert code == "level_middle_hit"
    assert w > 0
    code2, _ = level_match_score("Junior Python", "стажировка", "middle+")
    assert code2 == "level_junior_mismatch"


def test_single_site_synthesizes_targets():
    p = parse_and_validate_text(SAMPLE)
    targets = p.iter_targets()
    assert len(targets) == 1
    assert targets[0].site == "rabota.by"
    assert targets[0].location.city == "Минск"
    assert targets[0].search_area == "1002"


def test_multi_targets_json():
    p = validate_launch_dict(
        {
            "site": "rabota.by",
            "location": {"country": "Беларусь", "city": "Минск", "strict": True},
            "targets": [
                {
                    "site": "rabota.by",
                    "location": {
                        "country": "Беларусь",
                        "city": "Минск",
                        "strict": True,
                    },
                },
                {
                    "site": "hh.ru",
                    "location": {
                        "country": "Россия",
                        "city": "Москва",
                        "strict": False,
                    },
                },
            ],
            "queries": ["python"],
        }
    )
    assert len(p.iter_targets()) == 2
    assert p.site == "rabota.by"
    assert p.location.city == "Минск"
    by, ru = p.iter_targets()
    assert by.search_area == "1002"
    assert ru.site == "hh.ru"
    assert ru.search_area == "113"  # country-wide when strict=false
    assert ru.location.strict is False


def test_targets_dsl_parse_and_roundtrip():
    text = """
targets: rabota.by/Беларусь/Минск/true, hh.ru/Россия/Москва/false
queries: python developer
vacancy_limit: 12
"""
    p = parse_and_validate_text(text)
    assert len(p.targets) == 2
    assert p.site == "rabota.by"
    assert p.targets[1].search_area == "113"
    again = parse_and_validate_text(launch_to_strict_text(p))
    assert len(again.targets) == 2
    assert again.targets[0].site == "rabota.by"
    assert again.targets[1].site == "hh.ru"
    assert again.targets[1].location.strict is False
    assert again.vacancy_limit == 12


def test_target_site_country_mismatch():
    with pytest.raises((ValueError, ValidationError)):
        validate_launch_dict(
            {
                "queries": ["python"],
                "targets": [
                    {
                        "site": "rabota.by",
                        "location": {
                            "country": "Россия",
                            "city": "Москва",
                            "strict": True,
                        },
                    }
                ],
            }
        )
