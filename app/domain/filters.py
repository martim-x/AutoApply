"""Domain filters (pure functions)."""

from __future__ import annotations

import re
from typing import Any

from .entities import FilterResult

GOV_RE = re.compile(
    r"(?:https?://|www\.)?[^\s\"'<>]*\.gov\.[a-z]{2,}|(?:^|[^\w.-])gov\.[a-z]{2,}\b",
    re.IGNORECASE,
)

REMOTE_RE = re.compile(
    r"удал[её]нн\w*|remote|дистанц\w*|из\s*дома|work\s*from\s*home|\bwfh\b|"
    r"полностью\s*удал|full[\s-]*remote|remote[\s-]*first",
    re.IGNORECASE,
)

HYBRID_RE = re.compile(
    r"гибрид\w*|hybrid|частично\s*удал|remote\s*/\s*office|office\s*/\s*remote|"
    r"2[\s/]+3|3[\s/]+2.*(офис|office|удал)",
    re.IGNORECASE,
)

OFFICE_ONLY_RE = re.compile(
    r"только\s*(в\s*)?офис|офис\s*только|обязательн\w+\s*присутств|"
    r"полный\s*день\s*в\s*офисе|работа\s*в\s*офисе\s*обязательн|"
    r"office\s*only|on[\s-]*site\s*only|строго\s*офис|без\s*удал[её]н",
    re.IGNORECASE,
)

PYTHON_RE = re.compile(
    r"\bpython\b|питон|django|fastapi|flask|асинхронн\w*\s*python|"
    r"python[\s-]*(developer|разработчик|dev|engineer|инженер)|"
    r"(developer|разработчик|dev|engineer|инженер)[\s-]*python",
    re.IGNORECASE,
)

PYTHON_TITLE_STRONG_RE = re.compile(
    r"python[\s-]*(developer|разработчик|dev|engineer|инженер)|"
    r"python[\s-]*разработчик|python[\s-]*developer|"
    r"разработчик\s*\(?\s*python|developer\s*\(?\s*python",
    re.IGNORECASE,
)


def is_gov_related(url: str = "", text: str = "") -> bool:
    return bool(GOV_RE.search(f"{url or ''}\n{text or ''}"))


def is_remote_or_hybrid(title: str = "", text: str = "") -> bool:
    blob = f"{title or ''}\n{text or ''}"
    return bool(REMOTE_RE.search(blob) or HYBRID_RE.search(blob))


def looks_office_only(title: str = "", text: str = "") -> bool:
    return bool(OFFICE_ONLY_RE.search(f"{title or ''}\n{text or ''}"))


def has_python_signal(title: str = "", text: str = "") -> bool:
    return bool(PYTHON_RE.search(f"{title or ''}\n{text or ''}"))


def _location_blocked(title: str, description: str, location: Any) -> bool:
    """Strict mode: drop vacancies that clearly name another city."""
    from app.domain.launch_profile import location_match_score

    code, _w = location_match_score(title, description, location)
    return code == "location_other_city"


def evaluate_vacancy(
    url: str,
    title: str = "",
    description: str = "",
    *,
    require_remote_or_hybrid: bool = True,
    skip_gov: bool = True,
    require_python_keywords: bool = False,
    location: Any | None = None,
    launch: Any | None = None,
) -> FilterResult:
    blob = f"{title}\n{description}"

    if skip_gov and is_gov_related(url, blob):
        return FilterResult(False, "filtered:gov")

    if require_python_keywords and not has_python_signal(title, description):
        return FilterResult(False, "filtered:no_python")

    if require_remote_or_hybrid:
        remote_ok = is_remote_or_hybrid(title, description)
        if looks_office_only(title, description) and not remote_ok:
            return FilterResult(False, "filtered:office")
        if not remote_ok:
            return FilterResult(False, "filtered:office")

    loc = location or (getattr(launch, "location", None) if launch else None)
    if loc is not None and getattr(loc, "strict", False):
        if description and _location_blocked(title, description, loc):
            return FilterResult(False, "filtered:location")

    if launch is not None and getattr(launch, "salary_strict", False):
        from app.domain.launch_profile import salary_match_score

        code, _w = salary_match_score(
            title,
            description,
            salary_min_usd=getattr(launch, "salary_min_usd", None),
            salary_max_usd=getattr(launch, "salary_max_usd", None),
        )
        if code == "salary_below":
            return FilterResult(False, "filtered:salary")

    return FilterResult(True, "ok")
