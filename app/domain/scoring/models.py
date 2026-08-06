"""Scoring result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import FitCategory


@dataclass(frozen=True)
class SignalHit:
    id: str
    label: str
    weight: float
    fired: bool = True

    @property
    def polarity(self) -> str:
        if self.weight > 0:
            return "positive"
        if self.weight < 0:
            return "negative"
        return "neutral"


@dataclass
class ScoreBreakdown:
    category: FitCategory
    score: int
    total_weight: float
    contributions: list[SignalHit] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    explanation: str = ""

    @property
    def reason(self) -> str:
        return "+".join(self.reason_codes) if self.reason_codes else "no_signals"

    def top_positive(self, n: int = 3) -> list[SignalHit]:
        pos = [c for c in self.contributions if c.weight > 0]
        return sorted(pos, key=lambda c: c.weight, reverse=True)[:n]

    def top_negative(self, n: int = 3) -> list[SignalHit]:
        neg = [c for c in self.contributions if c.weight < 0]
        return sorted(neg, key=lambda c: c.weight)[:n]

    def as_dict(self) -> dict:
        return {
            "category": self.category.value,
            "score": self.score,
            "total_weight": round(self.total_weight, 4),
            "reason": self.reason,
            "explanation": self.explanation,
            "contributions": [
                {
                    "id": c.id,
                    "label": c.label,
                    "weight": c.weight,
                    "polarity": c.polarity,
                }
                for c in sorted(
                    self.contributions,
                    key=lambda x: abs(x.weight),
                    reverse=True,
                )
            ],
            "top_positive": [
                {"id": c.id, "label": c.label, "weight": c.weight}
                for c in self.top_positive()
            ],
            "top_negative": [
                {"id": c.id, "label": c.label, "weight": c.weight}
                for c in self.top_negative()
            ],
        }
