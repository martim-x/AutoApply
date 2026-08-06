"""Diverse explanation templates for score breakdowns."""

from __future__ import annotations

import hashlib
from typing import Any

from app.domain.scoring.models import ScoreBreakdown


_FALLBACK = {
    "HIGH": [
        "Сильный матч: {top_pos}. Итоговый вес {total:+.2f} → HIGH.",
        "Высокий fit за счёт {top_pos}; минусы слабые ({top_neg}).",
    ],
    "MEDIUM": [
        "Средний fit: плюсы {top_pos}, минусы {top_neg}. Вес {total:+.2f}.",
        "Частичное совпадение Legend: {top_pos}; сдерживает {top_neg}.",
    ],
    "LOW": [
        "Низкий fit: {top_neg}. Плюсы слабые ({top_pos}). Вес {total:+.2f}.",
        "Почему LOW — {top_neg}. Не хватает: {missing}.",
    ],
}


def _pick_template(templates: list[str], seed: str) -> str:
    if not templates:
        return "{top_pos} / {top_neg} → {total:+.2f}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(templates)
    return templates[idx]


def _fmt_hits(hits: list, empty: str = "нет явных") -> str:
    if not hits:
        return empty
    parts = [f"{h.label} ({h.weight:+.2f})" for h in hits[:3]]
    return ", ".join(parts)


def build_explanation(
    breakdown: ScoreBreakdown,
    *,
    templates: dict[str, Any] | None = None,
    title: str = "",
) -> str:
    cat = breakdown.category.value
    pool = list((templates or {}).get(cat) or _FALLBACK.get(cat) or [])
    seed = f"{cat}|{title}|{breakdown.reason}|{breakdown.total_weight:.3f}"
    tmpl = _pick_template(pool, seed)

    pos = breakdown.top_positive(3)
    neg = breakdown.top_negative(3)
    missing = "сильного Python-title / FastAPI·Django / remote"
    if any(c.id == "python_title_role" for c in breakdown.contributions):
        missing = "чистого remote или более полного стека Legend"
    if any(c.id in ("fastapi_match", "django_match") for c in breakdown.contributions):
        missing = "remote/hybrid без офис-only"

    try:
        return tmpl.format(
            top_pos=_fmt_hits(pos, "мало плюсов"),
            top_neg=_fmt_hits(neg, "критичных минусов нет"),
            total=breakdown.total_weight,
            pos_count=len([c for c in breakdown.contributions if c.weight > 0]),
            neg_count=len([c for c in breakdown.contributions if c.weight < 0]),
            missing=missing,
        )
    except Exception:
        return (
            f"{cat}: вес {breakdown.total_weight:+.2f}; "
            f"+ {_fmt_hits(pos)}; − {_fmt_hits(neg)}"
        )


def explanations_for_seed_variants(
    breakdown: ScoreBreakdown,
    *,
    templates: dict[str, Any] | None = None,
    n: int = 3,
) -> list[str]:
    """Helper for tests: collect up to n distinct template renders."""
    cat = breakdown.category.value
    pool = list((templates or {}).get(cat) or _FALLBACK.get(cat) or [])
    out: list[str] = []
    for i, tmpl in enumerate(pool[:n]):
        seed_bd = ScoreBreakdown(
            category=breakdown.category,
            score=breakdown.score,
            total_weight=breakdown.total_weight,
            contributions=list(breakdown.contributions),
            reason_codes=list(breakdown.reason_codes),
        )
        # force template by temporarily single-item pool via seed titles
        text = build_explanation(
            seed_bd,
            templates={cat: [tmpl]},
            title=f"variant-{i}-{breakdown.reason}",
        )
        out.append(text)
    return out
