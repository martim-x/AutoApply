"""Fit categorization: HIGH / MEDIUM / LOW via weighted feature graph."""

from __future__ import annotations

from .entities import CategoryResult
from .enums import FitCategory
from .scoring import score_vacancy


def categorize_vacancy(
    title: str = "",
    description: str = "",
    *,
    url: str = "",
) -> CategoryResult:
    """
    HIGH / MEDIUM / LOW from declarative weights (config/weights.json).
    Legend-oriented signals: Python role, FastAPI/Django, remote/hybrid, red flags.
    """
    breakdown = score_vacancy(title, description, url=url)
    return CategoryResult(
        category=breakdown.category,
        score=breakdown.score,
        reason=breakdown.reason,
        explanation=breakdown.explanation,
        contributions=tuple(
            {
                "id": c.id,
                "label": c.label,
                "weight": c.weight,
                "polarity": c.polarity,
            }
            for c in breakdown.contributions
        ),
        total_weight=breakdown.total_weight,
    )


def priority_key(category: FitCategory | str, score: int = 0) -> tuple[int, int]:
    if isinstance(category, FitCategory):
        order = category.priority
    else:
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(category), 9)
    return (order, -score)


def explain_vacancy(
    title: str = "",
    description: str = "",
    *,
    url: str = "",
) -> dict:
    """Full transparent breakdown for UI «Explain»."""
    return score_vacancy(title, description, url=url).as_dict()
