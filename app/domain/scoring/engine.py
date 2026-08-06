"""Weighted feature-graph scoring engine (declarative JSON map)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.domain.enums import FitCategory
from app.domain.scoring.explain import build_explanation
from app.domain.scoring.models import ScoreBreakdown, SignalHit

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEIGHTS_PATH = ROOT / "config" / "weights.json"


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for p in patterns:
        try:
            out.append(re.compile(p, re.IGNORECASE | re.MULTILINE))
        except re.error:
            continue
    return out


@lru_cache(maxsize=4)
def load_weight_map(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_WEIGHTS_PATH
    if not p.exists():
        return {
            "thresholds": {"high": 0.62, "medium": 0.38},
            "signals": {},
            "explain_templates": {},
        }
    data = json.loads(p.read_text(encoding="utf-8"))
    # precompile
    compiled: dict[str, Any] = {
        "thresholds": data.get("thresholds") or {"high": 0.62, "medium": 0.38},
        "explain_templates": data.get("explain_templates") or {},
        "signals": {},
        "source": data.get("source", ""),
        "version": data.get("version", 1),
    }
    for sid, spec in (data.get("signals") or {}).items():
        compiled["signals"][sid] = {
            **spec,
            "_patterns": _compile_patterns(list(spec.get("patterns") or [])),
        }
    return compiled


def reload_weight_map(path: str | None = None) -> dict[str, Any]:
    load_weight_map.cache_clear()
    return load_weight_map(path)


def _scope_text(scope: str, title: str, description: str, url: str) -> str:
    if scope == "title":
        return title
    if scope == "url":
        return url
    return f"{title}\n{description}\n{url}"


def _description_quality(description: str) -> bool:
    text = (description or "").strip()
    if len(text) < 400:
        return False
    # real JD markers vs SERP chrome
    markers = 0
    for token in (
        "обязаност",
        "требован",
        "стек",
        "задач",
        "responsib",
        "require",
        "fastapi",
        "django",
        "postgresql",
    ):
        if token in text.casefold():
            markers += 1
    return markers >= 2


def _signal_fires(
    sid: str,
    spec: dict[str, Any],
    title: str,
    description: str,
    url: str,
) -> bool:
    kind = spec.get("kind")
    if kind == "heuristic_description_quality":
        return _description_quality(description)
    blob = _scope_text(spec.get("scope") or "any", title, description, url)
    patterns: list[re.Pattern[str]] = spec.get("_patterns") or []
    return any(p.search(blob) for p in patterns)


def score_vacancy(
    title: str = "",
    description: str = "",
    *,
    url: str = "",
    weights_path: str | None = None,
    location: Any | None = None,
    launch: Any | None = None,
) -> ScoreBreakdown:
    """
    Aggregate signed weights in [-1, +1] per fired signal.
    Normalize to score 0..100 and map to HIGH / MEDIUM / LOW.
    Optional `launch` (LaunchProfile) adds geo / salary / level signals.
    """
    title = title or ""
    description = description or ""
    url = url or ""
    wmap = load_weight_map(weights_path)
    signals = wmap.get("signals") or {}

    fired: dict[str, SignalHit] = {}
    for sid, spec in signals.items():
        if _signal_fires(sid, spec, title, description, url):
            weight = float(spec.get("weight") or 0.0)
            weight = max(-1.0, min(1.0, weight))
            fired[sid] = SignalHit(
                id=sid,
                label=str(spec.get("label") or sid),
                weight=weight,
            )

    loc = location
    if launch is not None and loc is None:
        loc = getattr(launch, "location", None)

    if loc is not None:
        from app.domain.launch_profile import location_match_score

        code, weight = location_match_score(title, description, loc)
        labels = {
            "location_city_hit": "Город совпал с launch-профилем",
            "location_country_only": "Только страна (город не указан)",
            "location_other_city": "Другой город (строгое предпочтение)",
            "location_area_assumed": "Локация через area поиска",
            "location_unspecified": "Локация не уточнена в тексте",
        }
        if abs(weight) > 1e-9:
            fired[code] = SignalHit(
                id=code,
                label=labels.get(code, code),
                weight=max(-1.0, min(1.0, float(weight))),
            )

    if launch is not None:
        from app.domain.launch_profile import level_match_score, salary_match_score

        scode, sweight = salary_match_score(
            title,
            description,
            salary_min_usd=getattr(launch, "salary_min_usd", None),
            salary_max_usd=getattr(launch, "salary_max_usd", None),
        )
        salary_labels = {
            "salary_in_range": "Вилка пересекается с Legend ($)",
            "salary_below": "ЗП ниже вашей вилки",
            "salary_above": "ЗП выше верхней границы вилки",
            "salary_unknown": "ЗП не распознана",
            "salary_prefs_off": "Вилка не задана",
        }
        if abs(sweight) > 1e-9:
            fired[scode] = SignalHit(
                id=scode,
                label=salary_labels.get(scode, scode),
                weight=max(-1.0, min(1.0, float(sweight))),
            )

        lcode, lweight = level_match_score(
            title, description, getattr(launch, "level", "middle+") or "middle+"
        )
        level_labels = {
            "level_middle_hit": "Уровень Middle/Middle+ совпал",
            "level_senior_ok": "Senior-вакансия при цели Middle+",
            "level_junior_mismatch": "Junior при цели Middle+",
            "level_lead_heavy": "Lead/тимлид — тяжеловато",
            "level_unspecified": "Уровень неясен",
        }
        if abs(lweight) > 1e-9:
            fired[lcode] = SignalHit(
                id=lcode,
                label=level_labels.get(lcode, lcode),
                weight=max(-1.0, min(1.0, float(lweight))),
            )

    # suppress_if: drop signal when suppressors also fired
    for sid, spec in signals.items():
        if sid not in fired:
            continue
        suppressors = list(spec.get("suppress_if") or [])
        if suppressors and any(s in fired for s in suppressors):
            del fired[sid]

    # office_only softened if remote/hybrid also present
    if "office_only" in fired and ("remote_format" in fired or "hybrid_format" in fired):
        del fired["office_only"]

    contributions = list(fired.values())
    total = sum(c.weight for c in contributions)
    # squash to roughly [-1.2, +1.8] → 0..100
    clamped = max(-1.2, min(1.8, total))
    norm = (clamped + 1.2) / 3.0  # 0..1
    score = int(round(max(0, min(100, norm * 100))))

    thresholds = wmap.get("thresholds") or {}
    high_t = float(thresholds.get("high", 0.62))
    med_t = float(thresholds.get("medium", 0.38))
    # category from normalized total relative to useful range
    strength = max(0.0, min(1.0, (total + 0.4) / 1.6))
    if strength >= high_t and total >= 0.55:
        category = FitCategory.HIGH
    elif strength >= med_t and total >= 0.15:
        category = FitCategory.MEDIUM
    else:
        category = FitCategory.LOW

    # hard floors from strong negatives
    if any(c.id == "gov_marker" for c in contributions):
        category = FitCategory.LOW
        score = min(score, 25)
    if any(c.id == "location_other_city" for c in contributions):
        category = FitCategory.LOW
        score = min(score, 30)
    if any(c.id == "salary_below" for c in contributions):
        category = FitCategory.LOW if any(
            abs(c.weight) >= 0.8 for c in contributions if c.id == "salary_below"
        ) else category
        score = min(score, 40)
    if any(c.id == "office_only" for c in contributions) and not any(
        c.id in ("remote_format", "hybrid_format") for c in contributions
    ):
        category = FitCategory.LOW
        score = min(score, 35)

    reason_codes = [
        c.id for c in sorted(contributions, key=lambda x: abs(x.weight), reverse=True)
    ]
    breakdown = ScoreBreakdown(
        category=category,
        score=score,
        total_weight=total,
        contributions=contributions,
        reason_codes=reason_codes,
    )
    breakdown.explanation = build_explanation(
        breakdown,
        templates=wmap.get("explain_templates") or {},
        title=title,
    )
    return breakdown
