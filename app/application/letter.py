"""Cover letter helpers + human-like rate limiter."""

from __future__ import annotations

import random
import re
import time
from pathlib import Path


def render_letter(template: str, vacancy_name: str = "") -> str:
    def pick(m: re.Match) -> str:
        return random.choice(m.group(1).split("|"))

    text = re.sub(r"\{([^{}]+)\}", pick, template)
    text = text.replace("%(vacancy_name)s", vacancy_name or "вашу вакансию")
    return text.strip()


def load_letter(path: str | Path | None) -> str:
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8")
    return (
        "{Здравствуйте|Добрый день}!\n\n"
        "Меня заинтересовала вакансия %(vacancy_name)s. "
        "Кратко о себе: ответственный, быстро включаюсь в задачи.\n\n"
        "Буду рад обратной связи."
    )


class RateLimiter:
    def __init__(self, min_interval: float, jitter: float = 0.35) -> None:
        self.min_interval = min_interval
        self.jitter = jitter
        self._last = 0.0

    def wait(self, extra: float = 0.0) -> float:
        now = time.monotonic()
        delay = max(
            0.3,
            (self.min_interval + extra)
            * (1.0 + random.uniform(-self.jitter, self.jitter)),
        )
        sleep_for = delay - (now - self._last)
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last = time.monotonic()
        return max(0.0, sleep_for)
