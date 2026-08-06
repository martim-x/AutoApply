"""Assemble report payloads from UoW / launch config (no secrets)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.ports import UnitOfWork
from app.infrastructure.settings import Settings

ReportKind = Literal["work", "queue", "launch", "linkedin"]
REPORT_KINDS: tuple[str, ...] = ("work", "queue", "launch", "linkedin")


@dataclass
class ReportTheme:
    """Top-level PDF section (page-break between themes)."""

    title: str
    blocks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReportPayload:
    kind: str
    title: str
    profile: str
    app_name: str
    generated_at: float
    themes: list[ReportTheme] = field(default_factory=list)

    @property
    def generated_label(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.generated_at))


def normalize_kind(kind: str) -> str:
    k = (kind or "").strip().lower().removesuffix(".pdf")
    if k not in REPORT_KINDS:
        raise ValueError(f"unknown report kind: {kind!r}; expected one of {REPORT_KINDS}")
    return k


def assemble_report(
    uow: UnitOfWork,
    settings: Settings,
    kind: str,
    profile: str = "default",
) -> ReportPayload:
    kind = normalize_kind(kind)
    profile = uow.profiles.resolve_profile(profile)
    now = time.time()
    app_name = settings.app_name or "AutoApply"

    if kind == "work":
        return _work_report(uow, settings, profile, app_name, now)
    if kind == "queue":
        return _queue_report(uow, settings, profile, app_name, now)
    if kind == "linkedin":
        return _linkedin_report(uow, settings, profile, app_name, now)
    return _launch_report(uow, settings, profile, app_name, now)


def _enum_val(v: Any) -> str:
    return v.value if hasattr(v, "value") else str(v or "")


def _work_report(
    uow: UnitOfWork,
    settings: Settings,
    profile: str,
    app_name: str,
    now: float,
) -> ReportPayload:
    stats = uow.stats(profile)
    job = uow.jobs.get_status(profile)
    by_apply = stats.get("by_apply_status") or {}
    apps = stats.get("applications") or {}
    skipped = int(by_apply.get("skipped", 0)) + int(apps.get("skipped", 0))
    applied = int(stats.get("applied", 0) or apps.get("applied", 0))
    dry_run = int(apps.get("dry_run", 0) or by_apply.get("dry_run", 0))

    vacancies = uow.vacancies.list_for_profile(profile, limit=200)
    top = sorted(
        [v for v in vacancies if (_enum_val(v.filter_status) == "ok")],
        key=lambda v: (-int(v.score or 0), _enum_val(v.category)),
    )[:25]

    logs = uow.journal.recent(profile, limit=40)
    period_from = None
    if vacancies:
        created = [v.created_at for v in vacancies if v.created_at]
        if created:
            period_from = min(created)
    if period_from is None and logs:
        ts = [e.ts for e in logs if e.ts]
        if ts:
            period_from = min(ts)

    period_label = "всё время в БД"
    if period_from:
        period_label = (
            f"{time.strftime('%Y-%m-%d', time.localtime(period_from))}"
            f" — {time.strftime('%Y-%m-%d', time.localtime(now))}"
        )

    launch_summary = _launch_public_lines(settings)

    themes = [
        ReportTheme(
            title="Профиль и период",
            blocks=[
                {
                    "type": "kv",
                    "title": "Обзор",
                    "rows": [
                        ("Профиль", profile),
                        ("Период", period_label),
                        (
                            "Статус джоба",
                            _enum_val(job.status),
                        ),
                        ("Сообщение", (job.message or "—")[:200]),
                        ("Приложение", app_name),
                    ],
                },
                {
                    "type": "bullets",
                    "title": "Критерии запуска (без секретов)",
                    "items": launch_summary or ["launch.json не задан"],
                },
            ],
        ),
        ReportTheme(
            title="Статистика работы",
            blocks=[
                {
                    "type": "kv",
                    "title": "Категории (filter ok)",
                    "rows": [
                        ("HIGH", str(stats.get("high", 0))),
                        ("MEDIUM", str(stats.get("medium", 0))),
                        ("LOW", str(stats.get("low", 0))),
                        ("В очереди", str(stats.get("queued", 0))),
                    ],
                },
                {
                    "type": "kv",
                    "title": "Отклики",
                    "rows": [
                        ("Applied", str(applied)),
                        ("Dry-run", str(dry_run)),
                        ("Skipped", str(skipped)),
                        (
                            "По apply_status",
                            ", ".join(f"{k}:{v}" for k, v in sorted(by_apply.items()))
                            or "—",
                        ),
                    ],
                },
            ],
        ),
        ReportTheme(
            title="Топ вакансий",
            blocks=[
                {
                    "type": "table",
                    "title": "HIGH → score (до 25)",
                    "headers": ["Кат.", "Score", "Статус", "Вакансия"],
                    "rows": [
                        [
                            _enum_val(v.category),
                            str(v.score),
                            _enum_val(v.apply_status),
                            (v.title or v.url or "")[:90],
                        ]
                        for v in top
                    ]
                    or [["—", "—", "—", "нет данных"]],
                },
            ],
        ),
        ReportTheme(
            title="Журнал",
            blocks=[
                {
                    "type": "log",
                    "title": "Последние события",
                    "items": [
                        {
                            "when": time.strftime(
                                "%Y-%m-%d %H:%M:%S", time.localtime(e.ts)
                            )
                            if e.ts
                            else "",
                            "level": e.level,
                            "event": e.event,
                            "message": (e.message or "")[:160],
                        }
                        for e in logs
                    ]
                    or [
                        {
                            "when": "",
                            "level": "info",
                            "event": "empty",
                            "message": "записей нет",
                        }
                    ],
                },
            ],
        ),
    ]
    return ReportPayload(
        kind="work",
        title="Отчёт о проделанной работе",
        profile=profile,
        app_name=app_name,
        generated_at=now,
        themes=themes,
    )


def _queue_report(
    uow: UnitOfWork,
    settings: Settings,
    profile: str,
    app_name: str,
    now: float,
) -> ReportPayload:
    queued = uow.vacancies.next_queued(profile, limit=100)
    stats = uow.stats(profile)
    themes = [
        ReportTheme(
            title="Снимок очереди",
            blocks=[
                {
                    "type": "kv",
                    "title": "Сводка",
                    "rows": [
                        ("Профиль", profile),
                        ("Queued (filter ok)", str(stats.get("queued", 0))),
                        ("В выборке", str(len(queued))),
                        ("HIGH / MED / LOW", f"{stats.get('high', 0)} / {stats.get('medium', 0)} / {stats.get('low', 0)}"),
                    ],
                },
            ],
        ),
        ReportTheme(
            title="Вакансии в очереди",
            blocks=[
                {
                    "type": "table",
                    "title": "Очередь отклика",
                    "headers": ["Кат.", "Score", "Фильтр", "Вакансия", "URL"],
                    "rows": [
                        [
                            _enum_val(v.category),
                            str(v.score),
                            v.filter_status or "",
                            (v.title or "")[:70],
                            (v.url or "")[:70],
                        ]
                        for v in queued
                    ]
                    or [["—", "—", "—", "очередь пуста", ""]],
                },
            ],
        ),
    ]
    return ReportPayload(
        kind="queue",
        title="Очередь вакансий",
        profile=profile,
        app_name=app_name,
        generated_at=now,
        themes=themes,
    )


def _launch_report(
    uow: UnitOfWork,
    settings: Settings,
    profile: str,
    app_name: str,
    now: float,
) -> ReportPayload:
    from app.domain.launch_profile import load_launch_profile

    launch = load_launch_profile(settings.launch_path)
    pub = launch.to_public_dict() if launch else None
    loc = (pub or {}).get("location") or {}

    themes = [
        ReportTheme(
            title="Launch-профиль",
            blocks=[
                {
                    "type": "kv",
                    "title": "Параметры сайта и локации",
                    "rows": [
                        ("Профиль UI", profile),
                        ("Файл", str(settings.launch_path)),
                        ("Site", str((pub or {}).get("site") or "—")),
                        ("Country", str(loc.get("country") or "—")),
                        ("City", str(loc.get("city") or "—")),
                        ("Strict location", str(loc.get("strict", "—"))),
                        ("Level", str((pub or {}).get("level") or "—")),
                        (
                            "Salary USD",
                            _salary_label(pub) if pub else "—",
                        ),
                    ],
                },
                {
                    "type": "bullets",
                    "title": "Поисковые запросы",
                    "items": list((pub or {}).get("queries") or ["—"]),
                },
            ],
        ),
        ReportTheme(
            title="Фильтры",
            blocks=[
                {
                    "type": "kv",
                    "title": "Правила отбора (без секретов)",
                    "rows": [
                        (
                            "Remote/hybrid",
                            str((pub or {}).get("require_remote_or_hybrid", "—")),
                        ),
                        ("Skip gov", str((pub or {}).get("skip_gov", "—"))),
                        (
                            "Python keywords",
                            str((pub or {}).get("require_python_keywords", "—")),
                        ),
                        ("Apply limit", str((pub or {}).get("apply_limit", "—"))),
                        ("Dry run", str((pub or {}).get("dry_run", "—"))),
                        (
                            "Salary strict",
                            str((pub or {}).get("salary_strict", "—")),
                        ),
                    ],
                },
            ],
        ),
    ]
    return ReportPayload(
        kind="launch",
        title="Профиль запуска и фильтры",
        profile=profile,
        app_name=app_name,
        generated_at=now,
        themes=themes,
    )


def _linkedin_report(
    uow: UnitOfWork,
    settings: Settings,
    profile: str,
    app_name: str,
    now: float,
) -> ReportPayload:
    li_stats = uow.linkedin_contacts.stats(profile)
    vac_stats = uow.linkedin_vacancies.stats(profile)
    by_status = li_stats.get("by_status") or {}
    contacts = uow.linkedin_contacts.list_for_profile(profile, limit=40)
    vacancies = uow.linkedin_vacancies.list_for_profile(profile, limit=40)
    job = uow.jobs.get_status(profile)

    themes = [
        ReportTheme(
            title="LinkedIn — сводка",
            blocks=[
                {
                    "type": "kv",
                    "title": "Обзор",
                    "rows": [
                        ("Профиль", profile),
                        ("Приложение", app_name),
                        ("Статус джоба", _enum_val(job.status)),
                        ("Контакты", str(li_stats.get("total", 0))),
                        ("Вакансии LI", str(vac_stats.get("total", 0))),
                    ],
                },
                {
                    "type": "kv",
                    "title": "Контакты по статусу",
                    "rows": [
                        (str(k), str(v)) for k, v in sorted(by_status.items())
                    ]
                    or [("—", "нет данных")],
                },
            ],
        ),
        ReportTheme(
            title="Контакты",
            blocks=[
                {
                    "type": "table",
                    "title": "Последние контакты",
                    "headers": ["Статус", "Имя", "Запрос", "URL"],
                    "rows": [
                        [
                            _enum_val(c.status),
                            (c.name or "")[:60],
                            (c.query or "")[:40],
                            (c.url or "")[:70],
                        ]
                        for c in contacts
                    ]
                    or [["—", "—", "—", "нет данных"]],
                },
            ],
        ),
        ReportTheme(
            title="Вакансии LinkedIn",
            blocks=[
                {
                    "type": "table",
                    "title": "Собранные вакансии",
                    "headers": ["Вакансия", "Компания", "Локация", "URL"],
                    "rows": [
                        [
                            (v.title or "")[:70],
                            (v.company or "")[:40],
                            (v.location or "")[:40],
                            (v.url or "")[:70],
                        ]
                        for v in vacancies
                    ]
                    or [["—", "—", "—", "нет данных"]],
                },
            ],
        ),
    ]
    return ReportPayload(
        kind="linkedin",
        title="Отчёт LinkedIn",
        profile=profile,
        app_name=app_name,
        generated_at=now,
        themes=themes,
    )


def _salary_label(pub: dict[str, Any]) -> str:
    lo = pub.get("salary_min_usd")
    hi = pub.get("salary_max_usd")
    if lo is None and hi is None:
        return "—"
    return f"{lo or '?'}–{hi or '?'}"


def _launch_public_lines(settings: Settings) -> list[str]:
    from app.domain.launch_profile import load_launch_profile

    launch = load_launch_profile(settings.launch_path)
    if not launch:
        return []
    pub = launch.to_public_dict()
    loc = pub.get("location") or {}
    queries = ", ".join(pub.get("queries") or [])
    return [
        f"site: {pub.get('site')}",
        f"location: {loc.get('country')} / {loc.get('city')} (strict={loc.get('strict')})",
        f"level: {pub.get('level')}; salary: {_salary_label(pub)}",
        f"filters: remote={pub.get('require_remote_or_hybrid')}, "
        f"skip_gov={pub.get('skip_gov')}, python={pub.get('require_python_keywords')}",
        f"apply_limit={pub.get('apply_limit')}, dry_run={pub.get('dry_run')}",
        f"queries: {queries}" if queries else "queries: —",
    ]
