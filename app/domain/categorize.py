"""Fit categorization: HIGH / MEDIUM / LOW."""

from __future__ import annotations

import re

from .entities import CategoryResult
from .enums import FitCategory
from .filters import (
    PYTHON_TITLE_STRONG_RE,
    has_python_signal,
    is_remote_or_hybrid,
    looks_office_only,
)

SENIOR_OR_LEAD_RE = re.compile(
    r"\b(senior|lead|principal|staff|архитектор|тимлид|team\s*lead|head\s+of)\b",
    re.IGNORECASE,
)

WEAK_SIGNAL_RE = re.compile(
    r"стаж[её]р|intern|trainee|без\s*опыта|junior\+|middle\+|full[\s-]*stack|"
    r"1c|1с|битрикс|bitrix|wordpress|php\b|java\b(?!script)|c\+\+|frontend|"
    r"фронтенд|qa\b|тестировщик|devops|sre\b|data\s*analyst",
    re.IGNORECASE,
)

STRONG_STACK_RE = re.compile(
    r"\b(django|fastapi|flask|asyncio|pytest|sqlalchemy|celery|postgresql|"
    r"redis|docker|kubernetes|aiohttp|pydantic)\b",
    re.IGNORECASE,
)


def categorize_vacancy(
    title: str = "",
    description: str = "",
    *,
    url: str = "",
) -> CategoryResult:
    """
    HIGH: python developer/разработчик + remote/hybrid + strong match
    MEDIUM: partial python + remote/hybrid
    LOW: weak / crooked match
    """
    del url
    title = title or ""
    description = description or ""
    blob = f"{title}\n{description}"

    remote = is_remote_or_hybrid(title, description)
    python = has_python_signal(title, description)
    title_strong = bool(PYTHON_TITLE_STRONG_RE.search(title))
    strong_stack = bool(STRONG_STACK_RE.search(blob))
    weak = bool(WEAK_SIGNAL_RE.search(blob))
    office = looks_office_only(title, description) and not remote
    senior_heavy = bool(SENIOR_OR_LEAD_RE.search(title)) and not title_strong

    score = 0
    reasons: list[str] = []

    if title_strong:
        score += 45
        reasons.append("title:python_role")
    elif python:
        score += 25
        reasons.append("python_signal")
    else:
        score += 5
        reasons.append("weak_role")

    if remote:
        score += 30
        reasons.append("remote_or_hybrid")
    elif office:
        score -= 20
        reasons.append("office_only")
    else:
        score += 5
        reasons.append("format_unclear")

    if strong_stack:
        score += 20
        reasons.append("strong_stack")
    if weak:
        score -= 25
        reasons.append("weak_or_crooked")
    if senior_heavy:
        score -= 10
        reasons.append("senior_heavy_title")

    score = max(0, min(100, score))
    reason = "+".join(reasons) or "weak_match"

    if title_strong and remote and not weak and (strong_stack or score >= 85):
        return CategoryResult(FitCategory.HIGH, max(score, 90), reason)
    if title_strong and remote and not weak:
        return CategoryResult(FitCategory.HIGH, max(score, 88), reason)
    if python and remote and not weak and score >= 55:
        return CategoryResult(FitCategory.MEDIUM, score, reason)
    if python and remote:
        return CategoryResult(FitCategory.MEDIUM, min(score, 70), reason)
    return CategoryResult(FitCategory.LOW, min(score, 45), reason)


def priority_key(category: FitCategory | str, score: int = 0) -> tuple[int, int]:
    if isinstance(category, FitCategory):
        order = category.priority
    else:
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(category), 9)
    return (order, -score)
