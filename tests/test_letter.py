"""Cover letter templates: substitution, safe omission, no None leaks."""

from __future__ import annotations

from pathlib import Path

from app.application.letter import (
    load_letter_templates,
    pick_letter,
    render_letter,
)

ROOT = Path(__file__).resolve().parents[1]
LETTERS_DIR = ROOT / "letters"

IMPACT = (LETTERS_DIR / "style_1_impact.txt").read_text(encoding="utf-8")
PROJECT = (LETTERS_DIR / "style_3_project.txt").read_text(encoding="utf-8")


def test_company_substitution():
    out = render_letter(IMPACT, company="Яндекс", title="Python developer")
    assert "Яндекс" in out
    assert "интересна мне" in out
    assert "{company}" not in out
    assert "None" not in out


def test_missing_company_drops_sentence():
    out = render_letter(IMPACT, company="", title="Python developer")
    assert "интересна мне" not in out
    assert "{company}" not in out
    assert "None" not in out
    assert "Ваша компания" not in out
    assert "Готов разобрать кейсы" in out


def test_missing_company_none_string_drops_sentence():
    out = render_letter(IMPACT, company=None, title="Python")  # type: ignore[arg-type]
    assert "None" not in out
    assert "{company}" not in out
    out2 = render_letter(IMPACT, company="None", title="Python")
    assert "None" not in out2
    assert "интересна мне" not in out2


def test_project_inline_company_clause():
    with_co = render_letter(PROJECT, company="Acme")
    assert "в Acme" in with_co
    without = render_letter(PROJECT, company="")
    assert "Откликаюсь на позицию Python backend-разработчика." in without
    assert "в Acme" not in without
    assert "None" not in without


def test_double_brace_placeholder_not_left_wrapped():
    tpl = "{{#company}}Мне интересны задачи {{company}} в backend.{{/company}}\nГотов."
    out = render_letter(tpl, company="Acme")
    assert out == "Мне интересны задачи Acme в backend.\nГотов."
    assert "{Acme}" not in out


def test_unresolved_named_sentence_stripped():
    tpl = "База.\nКомпания {company} отличная.\nФинал."
    out = render_letter(tpl, company="")
    assert out == "База.\nФинал."
    assert "None" not in out


def test_choice_still_works():
    out = render_letter("{Привет|Привет}!\nТекст.", company="")
    assert out.startswith("Привет!")


def test_legacy_vacancy_name():
    out = render_letter("Вакансия: %(vacancy_name)s", vacancy_name="Backend")
    assert out == "Вакансия: Backend"


def test_bracket_company_substituted():
    tpl = "Откликаюсь на позицию Python backend-разработчика в [Компания].\nФинал."
    out = render_letter(tpl, company="Acme")
    assert "в Acme" in out
    assert "[Компания]" not in out


def test_bracket_company_missing_drops_sentence():
    tpl = "Откликаюсь на позицию Python backend-разработчика в [Компания].\nФинал."
    out = render_letter(tpl, company="")
    assert out == "Финал."
    assert "[" not in out
    assert "None" not in out


def test_unresolved_unknown_bracket_drops_sentence():
    tpl = (
        "Привет!\n"
        "[Компания] привлекает [конкретная причина из вакансии: продукт, "
        "архитектура, команда]. Готов рассказать про проекты на созвоне.\n"
        "С уважением,\nТимофей"
    )
    out = render_letter(tpl, company="")
    assert "[" not in out
    assert "привлекает" not in out
    assert "С уважением" in out
    assert "Тимофей" in out


def test_bracket_closing_sentence_survives():
    tpl = "[Компания] привлекает [причина]. Готов рассказать на созвоне."
    out = render_letter(tpl, company="Acme")
    assert out == "Готов рассказать на созвоне."
    assert "[" not in out


def test_load_and_pick_styles():
    templates = load_letter_templates(LETTERS_DIR)
    names = {n for n, _ in templates}
    assert "style_1_impact" in names
    assert "style_2_responsibility" in names
    assert "style_3_project" in names

    impact = pick_letter(templates, style="impact")
    assert "измеримый эффект" in impact.lower() or "Сильная сторона" in impact

    a = pick_letter(templates, style="rotate", seed="https://hh.ru/vacancy/1")
    b = pick_letter(templates, style="rotate", seed="https://hh.ru/vacancy/1")
    assert a == b


def test_shipped_templates_render_clean():
    for name, tpl in load_letter_templates(LETTERS_DIR):
        with_co = render_letter(tpl, company="TestCo", title="Python backend")
        without = render_letter(tpl, company="", title="Python backend")
        for text in (with_co, without):
            assert "None" not in text, name
            assert "{company}" not in text, name
            assert "{{" not in text, name
            assert "Тимофей" in text, name
            assert "Даниил" not in text, name
            assert "—" not in text, name
            assert "telegram" not in text.lower(), name
            assert "t.me" not in text.lower(), name
            assert "WhiteSnake" not in text, name
            assert "NEMIKA" not in text, name
            assert "Qdrant" not in text, name
            assert "LangChain" not in text, name
            assert "более 6 лет" not in text, name
