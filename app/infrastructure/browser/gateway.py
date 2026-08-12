"""Playwright browser gateway implementing BrowserGateway port."""

from __future__ import annotations

import re
import time
import traceback
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse

from app.application.alerts import AlertService, get_alert_service
from app.application.letter import (
    RateLimiter,
    load_letter_templates,
    pick_letter,
    render_letter,
)
from app.domain.categorize import categorize_vacancy
from app.domain.entities import Application, Vacancy
from app.domain.enums import ApplyStatus, FitCategory, JobStatus
from app.domain.filters import evaluate_vacancy
from app.domain.launch_profile import (
    LaunchProfile,
    SearchTarget,
    load_launch_profile,
)
from app.domain.parse_dedup import (
    is_duplicate_vacancy,
    next_dup_page_streak,
    next_old_streak,
    remember_vacancy,
    should_stop_dup_pages,
    should_stop_old_streak,
)
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.launch import (
    browser_context_kwargs,
    launch_chromium,
    user_facing_browser_error,
)
from app.infrastructure.browser.selectors import (
    SEL,
    VACANCY_DESCRIPTION_SELECTORS,
)
from app.infrastructure.settings import Settings

# Minimum length before accepting a description node (skip empty stubs).
_DESC_MIN_CHARS = 80

# Human-readable explanation per error status, shown in the journal and alerts.
STATUS_HINTS: dict[str, str] = {
    "error:no_submit": "кнопка «Отправить» не появилась на форме отклика — страница могла не дочитаться",
    "error:no_response_button": "кнопка «Откликнуться» не найдена — вакансия закрыта, страница не загрузилась или сработала защита",
    "error:unverified": "отклик, скорее всего, отправлен, но подтверждение «Вы откликнулись» не найдено — проверьте вручную",
    "error:click": "не удалось кликнуть по кнопке отклика",
    "error:timeout": "страница не ответила вовремя",
    "error:load": "не удалось загрузить страницу вакансии",
    "error:unknown": "непредвиденная ошибка",
    "need_manual": "требуется человек: работодатель задаёт вопросы в форме отклика",
    "captcha": "сработала защита от ботов — требуется человек",
    "archived": "вакансия в архиве — отклик невозможен",
    "load_fail": "страница вакансии не загрузилась за отведённое время",
    "unexpected": "непредвиденная ошибка во время отклика",
}


def _status_hint(status: str) -> str:
    for prefix, hint in STATUS_HINTS.items():
        if status == prefix or status.startswith(prefix + ":"):
            return hint
    return ""


def vacancy_id_from_url(url: str) -> str | None:
    m = re.search(r"/vacancy/(\d+)", url)
    return m.group(1) if m else None


def pick_vacancy_description(
    blocks: list[str],
    *,
    body_fallback: str = "",
    min_chars: int = _DESC_MIN_CHARS,
) -> str:
    """
    Prefer real vacancy description blocks over full-page body text.
    Used by _page_text; pure helper for unit tests.
    """
    for text in blocks:
        cleaned = (text or "").strip()
        if len(cleaned) >= min_chars:
            return cleaned[:80_000]
    return (body_fallback or "")[:80_000]


class PlaywrightBrowserGateway:
    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        alerts: AlertService | None = None,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.alerts = alerts or get_alert_service(settings)

    def _launch_profile(self) -> LaunchProfile | None:
        return load_launch_profile(self.settings.launch_path)

    def _site_base(
        self,
        launch: LaunchProfile | None = None,
        target: SearchTarget | None = None,
    ) -> str:
        if target is not None:
            return target.base_url
        lp = launch if launch is not None else self._launch_profile()
        return lp.base_url if lp else self.settings.base_url

    def _search_queries(self, launch: LaunchProfile | None = None) -> list[str]:
        lp = launch if launch is not None else self._launch_profile()
        return list(lp.queries) if lp else self.settings.search_list()

    def _search_area(
        self,
        launch: LaunchProfile | None = None,
        target: SearchTarget | None = None,
    ) -> str:
        if target is not None:
            return target.search_area
        lp = launch if launch is not None else self._launch_profile()
        return lp.search_area if lp else self.settings.search_area

    def _search_targets(
        self, launch: LaunchProfile | None = None
    ) -> list[SearchTarget | None]:
        """Targets for sequential SERP; [None] falls back to settings/primary."""
        lp = launch if launch is not None else self._launch_profile()
        if lp is None:
            return [None]
        return list(lp.iter_targets())

    def _filter_flags(self, launch: LaunchProfile | None = None) -> dict[str, Any]:
        lp = launch if launch is not None else self._launch_profile()
        s = self.settings
        if not lp:
            return {
                "require_remote_or_hybrid": s.require_remote_or_hybrid,
                "skip_gov": s.skip_gov,
                "require_python_keywords": s.require_python_keywords,
                "location": None,
                "launch": None,
                "vacancy_limit": s.vacancy_limit,
                "apply_limit": s.apply_limit,
                "dry_run": s.dry_run,
            }
        return {
            "require_remote_or_hybrid": lp.require_remote_or_hybrid,
            "skip_gov": lp.skip_gov,
            "require_python_keywords": lp.require_python_keywords,
            "location": lp.location,
            "launch": lp,
            "vacancy_limit": lp.vacancy_limit,
            "apply_limit": lp.apply_limit,
            "dry_run": lp.dry_run,
        }

    def run_login(self, profile: str, stop_flag: Any) -> None:
        from playwright.sync_api import sync_playwright

        uow = self.uow
        uow.jobs.set_status(
            profile, JobStatus.LOGGING_IN, f"Откройте браузер и войдите на {self._site_base()}"
        )
        uow.journal.log(profile, "login_start", "Старт логина")
        stop_flag.save_now = False

        with sync_playwright() as p:
            browser, context, sp = self._launch(p, profile)
            page = context.new_page()
            try:
                page.goto(
                    f"{self._site_base()}/account/login",
                    wait_until="domcontentloaded",
                )
                uow.jobs.set_status(
                    profile,
                    JobStatus.WAITING_USER,
                    "Войдите в аккаунт, затем нажмите «Сессия сохранена»",
                )
                deadline = time.time() + 600
                while time.time() < deadline and not stop_flag.stopped:
                    if getattr(stop_flag, "save_now", False):
                        break
                    url = page.url or ""
                    if "account/login" not in url and not url.rstrip("/").endswith("/login"):
                        page.wait_for_timeout(1500)
                        if "account/login" not in (page.url or ""):
                            break
                    time.sleep(0.5)

                if stop_flag.stopped and not getattr(stop_flag, "save_now", False):
                    uow.jobs.set_status(profile, JobStatus.IDLE, "Логин отменён")
                    return

                context.storage_state(path=str(sp))
                uow.profiles.save_session(profile, sp)
                uow.journal.log(profile, "session_saved", f"Сессия → {sp}")
                uow.jobs.set_status(profile, JobStatus.DONE, f"Сессия сохранена: {sp.name}")
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    def run_search(self, profile: str, stop_flag: Any) -> None:
        from playwright.sync_api import sync_playwright

        s = self.settings
        uow = self.uow
        launch = self._launch_profile()
        flags = self._filter_flags(launch)
        sp = s.state_path(profile)
        if not sp.exists():
            uow.jobs.set_status(profile, JobStatus.ERROR, "Нет сессии — сначала Login")
            uow.journal.log(profile, "search_abort", "нет storage_state", level="error")
            self.alerts.notify_error(
                profile, "Нет сессии — сначала Login", event="search_abort"
            )
            return

        targets = self._search_targets(launch)
        target_labels = []
        for t in targets:
            if t is None:
                target_labels.append(f"area={self._search_area(launch)}")
            else:
                target_labels.append(f"{t.site}/{t.location.city}(area={t.search_area})")
        vacancy_limit = int(flags["vacancy_limit"])
        uow.jobs.set_status(
            profile,
            JobStatus.SEARCHING,
            f"Поиск вакансий… до {vacancy_limit} "
            f"({len(targets)} target(s): {', '.join(target_labels)})",
        )
        queries = self._search_queries(launch)
        uow.journal.log(
            profile,
            "search_start",
            f"targets={target_labels} vacancy_limit={vacancy_limit} queries={queries}",
        )
        limiter = RateLimiter(s.min_action_interval, s.jitter)
        found = 0
        kept = 0
        processed = 0
        walk = s.serp_walk_knobs()
        streak_stop = int(walk["old_streak_stop"])
        max_pages = int(walk["max_serp_pages"])
        dup_page_stop = int(walk["dup_page_stop"])
        known_urls, known_ids = uow.vacancies.known_keys(profile)

        with sync_playwright() as p:
            browser, context, spath = self._launch(p, profile)
            page = context.new_page()
            try:
                seen: set[str] = set()
                aborted_blocker = False
                # Same HH storage_state for rabota.by + hh.ru; sequential per target.
                for ti, target in enumerate(targets):
                    if stop_flag.stopped or aborted_blocker or kept >= vacancy_limit:
                        break
                    site = (
                        target.site
                        if target is not None
                        else (launch.site if launch else s.base_url)
                    )
                    area = self._search_area(launch, target)
                    target_location = (
                        target.location
                        if target is not None
                        else flags.get("location")
                    )
                    uow.journal.log(
                        profile,
                        "search_target",
                        f"[{ti+1}/{len(targets)}] site={site} area={area}",
                        payload={
                            "site": str(site),
                            "area": area,
                            "strict": bool(
                                getattr(target_location, "strict", True)
                            ),
                        },
                    )
                    for qi, query in enumerate(queries):
                        if (
                            stop_flag.stopped
                            or aborted_blocker
                            or kept >= vacancy_limit
                        ):
                            break
                        uow.journal.log(
                            profile,
                            "serp",
                            f"[{site}] [{qi+1}/{len(queries)}] {query!r}",
                        )
                        checkpoint = {
                            **uow.stats(profile),
                            "last_query": query,
                            "last_site": str(site),
                            "processed_count": processed,
                            "kept": kept,
                            "found": found,
                        }
                        uow.jobs.set_status(
                            profile,
                            JobStatus.SEARCHING,
                            f"Поиск [{site}]: {query} ({qi+1}/{len(queries)}) — "
                            f"{kept}/{vacancy_limit} подходящих",
                            stats=checkpoint,
                        )
                        try:
                            dup_page_streak = 0
                            query_stop = False
                            for page_idx in range(max_pages):
                                if (
                                    stop_flag.stopped
                                    or kept >= vacancy_limit
                                    or aborted_blocker
                                    or query_stop
                                ):
                                    break
                                serp = self._serp_url(
                                    query, launch, page=page_idx, target=target
                                )
                                if not self._goto(
                                    page, serp, limiter, expect=SEL["vacancy_link"]
                                ):
                                    uow.journal.log(
                                        profile,
                                        "serp_fail",
                                        f"{query} page={page_idx}",
                                        level="warn",
                                    )
                                    self.alerts.notify(
                                        "serp_fail",
                                        f"SERP failed: {query}",
                                        profile=profile,
                                        details={"query": query, "page": page_idx},
                                    )
                                    break

                                blocker = self._detect_blockers(page)
                                if blocker:
                                    self._pause_for_blocker(
                                        profile,
                                        blocker,
                                        context=f"search query={query!r} page={page_idx}",
                                    )
                                    if hasattr(stop_flag, "stop"):
                                        stop_flag.stop()
                                    aborted_blocker = True
                                    break

                                items = self._collect_links(page, limit=50)
                                if not items:
                                    break

                                page_rows: list[tuple[dict[str, str], str | None, bool]] = []
                                for item in items:
                                    path = urlparse(item["url"]).path
                                    if path in seen:
                                        continue
                                    seen.add(path)
                                    found += 1
                                    url = item["url"]
                                    vid = vacancy_id_from_url(url)
                                    is_dup = is_duplicate_vacancy(
                                        url=url,
                                        vacancy_id=vid,
                                        known_urls=known_urls,
                                        known_ids=known_ids,
                                    )
                                    page_rows.append((item, vid, is_dup))

                                if not page_rows:
                                    break

                                new_on_page = 0
                                old_streak = 0
                                for item, vid, is_dup in page_rows:
                                    if stop_flag.stopped or kept >= vacancy_limit:
                                        break
                                    url = item["url"]
                                    title = item["title"] or item["url"]
                                    try:
                                        if is_dup:
                                            old_streak = next_old_streak(old_streak, True)
                                            uow.journal.log(
                                                profile,
                                                "filtered:duplicate",
                                                title[:80],
                                                payload={
                                                    "url": url,
                                                    "vacancy_id": vid,
                                                    "page": page_idx,
                                                },
                                            )
                                            if should_stop_old_streak(
                                                old_streak, streak_stop
                                            ):
                                                uow.journal.log(
                                                    profile,
                                                    "early_stop:old_streak",
                                                    f"streak={old_streak} query={query!r}",
                                                    payload={
                                                        "streak": old_streak,
                                                        "threshold": streak_stop,
                                                        "query": query,
                                                        "page": page_idx,
                                                    },
                                                )
                                                query_stop = True
                                                break
                                            continue

                                        old_streak = next_old_streak(old_streak, False)
                                        new_on_page += 1

                                        pre = evaluate_vacancy(
                                            url,
                                            title,
                                            "",
                                            require_remote_or_hybrid=False,
                                            skip_gov=bool(flags["skip_gov"]),
                                            require_python_keywords=False,
                                            location=None,
                                        )
                                        if not pre.ok:
                                            uow.vacancies.upsert(
                                                Vacancy(
                                                    profile=profile,
                                                    url=url,
                                                    vacancy_id=vid,
                                                    title=title,
                                                    query=query,
                                                    serp_url=serp,
                                                    category=FitCategory.LOW,
                                                    filter_status=pre.status,
                                                    apply_status=ApplyStatus.SKIPPED,
                                                )
                                            )
                                            remember_vacancy(
                                                url=url,
                                                vacancy_id=vid,
                                                known_urls=known_urls,
                                                known_ids=known_ids,
                                            )
                                            processed += 1
                                            continue

                                        loaded = self._goto(
                                            page, url, limiter, expect=SEL["response_btn"]
                                        )
                                        page_text = self._page_text(page) if loaded else ""
                                        card_blocker = self._detect_blockers(page)
                                        if card_blocker:
                                            self._pause_for_blocker(
                                                profile,
                                                card_blocker,
                                                context=f"vacancy {title[:60]}",
                                            )
                                            if hasattr(stop_flag, "stop"):
                                                stop_flag.stop()
                                            aborted_blocker = True
                                            break

                                        decision = evaluate_vacancy(
                                            url,
                                            title,
                                            page_text,
                                            require_remote_or_hybrid=bool(
                                                flags["require_remote_or_hybrid"]
                                            ),
                                            skip_gov=bool(flags["skip_gov"]),
                                            require_python_keywords=bool(
                                                flags["require_python_keywords"]
                                            ),
                                            location=target_location,
                                            launch=flags.get("launch"),
                                        )
                                        cat = categorize_vacancy(
                                            title,
                                            page_text,
                                            url=url,
                                            location=target_location,
                                            launch=flags.get("launch"),
                                        )
                                        ok = decision.ok
                                        uow.vacancies.upsert(
                                            Vacancy(
                                                profile=profile,
                                                url=url,
                                                vacancy_id=vid,
                                                title=title,
                                                description=page_text[:5000],
                                                query=query,
                                                serp_url=serp,
                                                category=cat.category,
                                                score=cat.score,
                                                category_reason=cat.explanation
                                                or cat.reason,
                                                filter_status="ok"
                                                if ok
                                                else decision.status,
                                                apply_status=ApplyStatus.QUEUED
                                                if ok
                                                else ApplyStatus.SKIPPED,
                                            )
                                        )
                                        remember_vacancy(
                                            url=url,
                                            vacancy_id=vid,
                                            known_urls=known_urls,
                                            known_ids=known_ids,
                                        )
                                        processed += 1
                                        if ok:
                                            kept += 1
                                            uow.journal.log(
                                                profile,
                                                "queued",
                                                f"[{cat.category.value}/{cat.score}] "
                                                f"{title[:70]}",
                                            )
                                        else:
                                            uow.journal.log(
                                                profile, decision.status, title[:80]
                                            )

                                        try:
                                            self._goto(
                                                page,
                                                serp,
                                                limiter,
                                                expect=SEL["vacancy_link"],
                                            )
                                        except Exception:
                                            pass
                                    except Exception as unit_exc:
                                        uow.journal.log(
                                            profile,
                                            "unit_failed",
                                            f"{title[:60]}: {unit_exc}",
                                            level="warn",
                                            payload={"url": url, "query": query},
                                        )
                                        self.alerts.notify(
                                            "unit_failed",
                                            str(unit_exc)[:200],
                                            profile=profile,
                                            details={"url": url, "query": query},
                                        )
                                        continue

                                if aborted_blocker or query_stop:
                                    break

                                page_all_dup = new_on_page == 0
                                dup_page_streak = next_dup_page_streak(
                                    dup_page_streak, page_all_dup
                                )
                                if page_all_dup:
                                    uow.journal.log(
                                        profile,
                                        "serp_skip_dup_page",
                                        f"page={page_idx} query={query!r} "
                                        f"dup_pages={dup_page_streak}",
                                        payload={
                                            "page": page_idx,
                                            "query": query,
                                            "dup_page_streak": dup_page_streak,
                                            "listings": len(page_rows),
                                        },
                                    )
                                    if should_stop_dup_pages(
                                        dup_page_streak, dup_page_stop
                                    ):
                                        uow.journal.log(
                                            profile,
                                            "early_stop:dup_pages",
                                            f"dup_pages={dup_page_streak} "
                                            f"query={query!r}",
                                            payload={
                                                "dup_page_streak": dup_page_streak,
                                                "threshold": dup_page_stop,
                                                "query": query,
                                                "page": page_idx,
                                            },
                                        )
                                        break

                            if kept >= vacancy_limit or aborted_blocker:
                                break
                        except Exception as query_exc:
                            # Per-query isolation: keep other queries / saved vacancies
                            uow.journal.log(
                                profile,
                                "unit_failed",
                                f"query={query!r}: {query_exc}",
                                level="warn",
                                payload={"query": query},
                            )
                            self.alerts.notify(
                                "unit_failed",
                                f"query failed: {query}",
                                profile=profile,
                                details={"query": query, "error": str(query_exc)[:200]},
                            )
                            continue

                try:
                    context.storage_state(path=str(spath))
                    uow.profiles.save_session(profile, spath)
                except Exception:
                    pass

                stats = {
                    **uow.stats(profile),
                    "processed_count": processed,
                    "kept": kept,
                    "found": found,
                }
                current = uow.jobs.get_status(profile)
                if current.status == JobStatus.WAITING_USER:
                    # Captcha / need_manual already set status + alert
                    pass
                else:
                    msg = (
                        f"SERP найдено: {found}; оставлено в очереди: {kept}; "
                        f"лимит поиска: {vacancy_limit}"
                    )
                    status = JobStatus.IDLE if stop_flag.stopped else JobStatus.DONE
                    if stop_flag.stopped and not aborted_blocker:
                        msg = "Поиск остановлен. " + msg
                    uow.jobs.set_status(profile, status, msg, stats=stats)
                    uow.journal.log(profile, "search_done", msg, payload=stats)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    def run_apply(self, profile: str, stop_flag: Any) -> None:
        from playwright.sync_api import sync_playwright

        s = self.settings
        uow = self.uow
        flags = self._filter_flags()
        if not s.state_path(profile).exists():
            uow.jobs.set_status(profile, JobStatus.ERROR, "Нет сессии — сначала Login")
            self.alerts.notify_error(
                profile, "Нет сессии — сначала Login", event="session_lost"
            )
            return

        ok, reason = self._under_quota(profile)
        if not ok:
            uow.jobs.set_status(profile, JobStatus.ERROR, reason)
            return

        apply_limit = int(flags["apply_limit"])
        queue = uow.vacancies.next_queued(profile, limit=apply_limit)
        if not queue:
            uow.jobs.set_status(profile, JobStatus.DONE, "Очередь пуста — сначала Search")
            return

        templates = load_letter_templates(s.letter_path)
        letter_style = (s.letter_style or "rotate").strip().lower()
        limiter = RateLimiter(s.min_action_interval, s.jitter)
        dry_run = bool(flags["dry_run"])
        uow.jobs.set_status(
            profile,
            JobStatus.APPLYING,
            f"Отклик: все найденные в очереди — {len(queue)} "
            f"(лимит {apply_limit}, HIGH→MEDIUM→LOW)"
            + (" [DRY-RUN]" if dry_run else ""),
            stats=uow.stats(profile),
        )
        uow.journal.log(
            profile,
            "apply_start",
            f"queue={len(queue)} apply_limit={apply_limit} dry_run={dry_run}",
        )
        applied = 0
        processed = 0

        with sync_playwright() as p:
            browser, context, spath = self._launch(p, profile)
            page = context.new_page()
            try:
                for vac in queue:
                    if stop_flag.stopped:
                        break
                    ok, reason = self._under_quota(profile)
                    if not ok:
                        uow.journal.log(profile, "quota", reason, level="warn")
                        break

                    assert vac.id is not None
                    title = vac.title or vac.url
                    cat = vac.category.value
                    uow.jobs.set_status(
                        profile,
                        JobStatus.APPLYING,
                        f"[{cat}] {title[:60]}",
                        stats={
                            **uow.stats(profile),
                            "processed_count": processed,
                            "applied_run": applied,
                        },
                    )

                    try:
                        if uow.applications.already_applied(profile, vac.url):
                            uow.vacancies.set_apply_status(vac.id, "skipped")
                            processed += 1
                            continue

                        t0 = time.time()
                        loaded = self._goto(
                            page, vac.url, limiter, expect=SEL["response_btn"]
                        )
                        if not loaded:
                            status, attempts = "load_fail", 1
                        else:
                            # Queue already went through evaluate_vacancy during
                            # search (filter_status=ok); don't re-filter here —
                            # it drops good python vacancies (title-only gate).
                            company = self._company_from_page(page)
                            template = pick_letter(
                                templates,
                                style=letter_style,
                                seed=vac.url or title,
                            )
                            letter = render_letter(
                                template,
                                title=title,
                                company=company,
                                vacancy_name=title,
                            )
                            status = "error:unknown"
                            attempts = 0
                            saw_unverified = False
                            saw_apply_error = False
                            self._last_letter_filled = False
                            for attempts in range(1, s.apply_retries + 1):
                                status = self._try_apply_once(page, letter, dry_run)
                                if status == "error:unverified":
                                    saw_unverified = True
                                if str(status).startswith("error:"):
                                    saw_apply_error = True
                                if status in (
                                    "applied", "skipped", "archived", "dry_run",
                                    "need_manual", "captcha",
                                ):
                                    break
                                if attempts < s.apply_retries:
                                    self._goto(
                                        page,
                                        vac.url,
                                        limiter,
                                        expect=SEL["response_btn"],
                                    )
                                    time.sleep(s.load_retry_delay)
                            # "skipped" means the after-apply block was seen; if an
                            # earlier attempt errored, that response is ours.
                            if status == "skipped" and (
                                saw_apply_error or saw_unverified
                            ):
                                status = "applied"

                        duration_ms = int((time.time() - t0) * 1000)
                        # Persist attempt immediately (survives mid-run crash)
                        uow.applications.record(
                            Application(
                                profile=profile,
                                vacancy_url=vac.url,
                                vacancy_id=vacancy_id_from_url(vac.url),
                                title=title,
                                category=cat,
                                status=status,
                                attempt=attempts,
                                error=(
                                    None
                                    if not str(status).startswith("error:")
                                    else status
                                ),
                                dry_run=dry_run,
                                duration_ms=duration_ms,
                            )
                        )

                        if status in ("applied", "dry_run"):
                            uow.vacancies.set_apply_status(
                                vac.id,
                                "applied" if status == "applied" else "dry_run",
                            )
                            applied += 1
                            limiter.wait(
                                extra=s.after_apply_delay - s.min_action_interval
                            )
                        elif status.startswith("filtered:") or status in (
                            "skipped", "archived"
                        ):
                            uow.vacancies.set_apply_status(vac.id, "skipped")
                        elif status in ("need_manual", "captcha"):
                            uow.vacancies.set_apply_status(vac.id, "queued")
                            self._pause_for_blocker(
                                profile, status, context=title[:80]
                            )
                            if hasattr(stop_flag, "stop"):
                                stop_flag.stop()
                            break
                        else:
                            uow.vacancies.set_apply_status(vac.id, "failed")
                            if str(status).startswith("error:"):
                                self.alerts.notify_error(
                                    profile,
                                    f"{status}: {title[:60]}",
                                    event="error",
                                    details={
                                        "url": vac.url,
                                        "status": status,
                                        "hint": _status_hint(status),
                                    },
                                )

                        processed += 1
                        hint = _status_hint(status)
                        msg = f"[{cat}] {title[:70]}"
                        if hint:
                            msg += f" — {hint}"
                        payload: dict[str, Any] = {
                            "url": vac.url,
                            "status": status,
                            "hint": hint,
                            "letter_filled": getattr(
                                self, "_last_letter_filled", False
                            ),
                            "domain": (
                                urlparse(vac.url).netloc if vac.url else ""
                            ),
                        }
                        if str(status).startswith("error:"):
                            payload["debug"] = self._apply_debug(page)
                        uow.journal.log(profile, status, msg, payload=payload)

                        if status == "applied" and not dry_run:
                            chat_result = self._send_chat_followup(
                                page, vac.url, letter, limiter, s, title=title
                            )
                            if chat_result == "chat_sent":
                                uow.journal.log(
                                    profile,
                                    "chat_sent",
                                    f"Сопроводительное отправлено в чат — {title[:60]}",
                                    payload={
                                        "url": vac.url,
                                        "domain": urlparse(vac.url).netloc,
                                    },
                                )
                            elif s.chat_after_apply:
                                uow.journal.log(
                                    profile,
                                    "chat_skipped",
                                    f"Чат с работодателем недоступен — {title[:60]}",
                                    payload={
                                        "url": vac.url,
                                        "reason": "no chat or employer disabled it",
                                    },
                                )
                    except Exception as unit_exc:
                        uow.journal.log(
                            profile,
                            "unit_failed",
                            f"{title[:60]}: {unit_exc}",
                            level="warn",
                            payload={"url": vac.url},
                        )
                        try:
                            uow.vacancies.set_apply_status(vac.id, "failed")
                        except Exception:
                            pass
                        self.alerts.notify(
                            "unit_failed",
                            str(unit_exc)[:200],
                            profile=profile,
                            details={"url": vac.url},
                        )
                        processed += 1
                        continue

                try:
                    context.storage_state(path=str(spath))
                    uow.profiles.save_session(profile, spath)
                except Exception:
                    pass

                stats = {
                    **uow.stats(profile),
                    "processed_count": processed,
                    "applied_run": applied,
                }
                current = uow.jobs.get_status(profile)
                if current.status == JobStatus.WAITING_USER:
                    pass
                elif stop_flag.stopped:
                    uow.jobs.set_status(
                        profile,
                        JobStatus.IDLE,
                        f"Остановлено. Откликов: {applied}",
                        stats=stats,
                    )
                else:
                    uow.jobs.set_status(
                        profile,
                        JobStatus.DONE,
                        f"Готово. Откликов за прогон: {applied}",
                        stats=stats,
                    )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    # ── helpers ───────────────────────────────────────────────

    def _launch(self, p, profile: str):
        s = self.settings
        sp = s.state_path(profile)
        kwargs = browser_context_kwargs(s, locale="ru-RU")
        browser = launch_chromium(p, headless=s.effective_headless())
        if sp.exists():
            context = browser.new_context(storage_state=str(sp), **kwargs)
        else:
            context = browser.new_context(**kwargs)
        context.set_default_navigation_timeout(s.navigation_timeout_ms)
        context.set_default_timeout(s.content_timeout_ms)
        return browser, context, sp

    def _serp_url(
        self,
        query: str,
        launch: LaunchProfile | None = None,
        *,
        page: int = 0,
        target: SearchTarget | None = None,
    ) -> str:
        base = self._site_base(launch, target)
        area = self._search_area(launch, target)
        url = f"{base}/search/vacancy?text={quote_plus(query)}&items_on_page=50"
        if area:
            url += f"&area={area}"
        # Newest-first so page walk past known listings is meaningful
        url += "&order_by=publication_time"
        if page > 0:
            url += f"&page={int(page)}"
        return url

    def _under_quota(self, profile: str) -> tuple[bool, str]:
        s = self.settings
        now = time.time()
        hour = self.uow.applications.count_applied_since(profile, now - 3600)
        day = self.uow.applications.count_applied_since(profile, now - 86400)
        if hour >= s.max_per_hour:
            return False, f"лимит часа ({hour}/{s.max_per_hour})"
        if day >= s.max_per_day:
            return False, f"лимит суток ({day}/{s.max_per_day})"
        return True, ""

    def _page_looks_loaded(self, page) -> bool:
        try:
            ready = page.evaluate("document.readyState")
            if ready not in ("interactive", "complete"):
                return False
            text_len = len((page.locator("body").inner_text(timeout=2000) or "").strip())
            return text_len > 80
        except Exception:
            return False

    def _normalize_vacancy_url(self, url: str) -> str:
        """Switch hh.ru (RU) links to the profile's site (rabota.by etc.)."""
        if not url:
            return url
        try:
            parsed = urlparse(url)
            if parsed.netloc not in ("hh.ru", "www.hh.ru", "rabota.by", "www.rabota.by"):
                return url
            base = self._site_base()
            domain = urlparse(base).netloc
            if not domain or parsed.netloc == domain:
                return url
            return urlunparse(parsed._replace(netloc=domain, scheme="https"))
        except Exception:
            return url

    @staticmethod
    def _confirm_relocation_warning(page) -> None:
        """Click «Все равно откликнуться» on the cross-country warning dialog."""
        try:
            loc = page.locator(SEL["relocation_confirm"])
            for i in range(min(loc.count(), 2)):
                try:
                    if loc.nth(i).is_visible(timeout=800):
                        loc.nth(i).click(timeout=2_000)
                        return
                except Exception:
                    continue
        except Exception:
            pass

    def _goto(self, page, url: str, limiter: RateLimiter, *, expect: str | None = None) -> bool:
        from playwright.sync_api import TimeoutError as PwTimeout

        s = self.settings
        url = self._normalize_vacancy_url(url)
        last_err: Exception | None = None
        for attempt in range(1, s.load_retries + 1):
            limiter.wait()
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(s.settle_ms)
                if expect:
                    try:
                        page.wait_for_selector(expect, timeout=s.content_timeout_ms)
                    except PwTimeout:
                        pass
                if self._page_looks_loaded(page):
                    return True
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(s.settle_ms)
                if self._page_looks_loaded(page):
                    return True
                time.sleep(s.load_retry_delay * attempt)
            except Exception as e:
                last_err = e
                time.sleep(s.load_retry_delay * attempt)
        if last_err:
            raise last_err
        return False

    def _collect_links(self, page, limit: int) -> list[dict[str, str]]:
        from playwright.sync_api import TimeoutError as PwTimeout

        items: list[dict[str, str]] = []
        seen: set[str] = set()
        try:
            page.wait_for_selector(SEL["vacancy_link"], timeout=15_000)
        except PwTimeout:
            pass
        links = page.locator(SEL["vacancy_link"])
        n = min(links.count(), max(limit * 3, limit))
        for i in range(n):
            if len(items) >= limit:
                break
            a = links.nth(i)
            try:
                href = a.get_attribute("href") or ""
                title = (a.inner_text(timeout=2000) or "").strip()
            except Exception:
                continue
            if "/vacancy/" not in href:
                continue
            full = urljoin(page.url, href).split("?")[0]
            path = urlparse(full).path
            if path in seen:
                continue
            seen.add(path)
            items.append({"url": full, "title": title})
        return items

    def _detect_blockers(self, page) -> str | None:
        url = page.url or ""
        if "account/login" in url or url.rstrip("/").endswith("/login"):
            return "need_manual"
        try:
            loc = page.locator(SEL["captcha"])
            for i in range(min(loc.count(), 3)):
                try:
                    if loc.nth(i).is_visible(timeout=500):
                        return "captcha"
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _pause_for_blocker(
        self, profile: str, blocker: str, *, context: str = ""
    ) -> None:
        """Unify captcha / need_manual: journal + WAITING_USER + SMTP + stop."""
        msg = f"Нужен человек: {blocker}"
        if context:
            msg = f"{msg} ({context})"
        self.uow.jobs.set_status(profile, JobStatus.WAITING_USER, msg)
        self.uow.journal.log(profile, blocker, msg, level="warn")
        if blocker == "captcha":
            self.alerts.notify_captcha(profile, msg, details={"blocker": blocker})
        else:
            self.alerts.notify(
                blocker,
                msg,
                profile=profile,
                details={"blocker": blocker},
            )

    @staticmethod
    def _looks_archived(page) -> bool:
        """HH archives closed vacancies — no response button is rendered."""
        for text in ("Вакансия в архиве", "В архиве с", "в архиве с"):
            try:
                loc = page.get_by_text(text, exact=False)
                if loc.count() and loc.first.is_visible(timeout=600):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _apply_debug(page) -> dict[str, Any]:
        """Snapshot of the page state when an apply error happens."""
        out: dict[str, Any] = {"page_url": "", "selectors": {}}
        try:
            out["page_url"] = page.url
        except Exception:
            pass
        for key in (
            "response_form",
            "submit_response",
            "already",
            "chat_link",
            "response_btn",
            "letter_toggle",
            "response_success",
        ):
            try:
                out["selectors"][key] = page.locator(SEL[key]).count()
            except Exception:
                out["selectors"][key] = -1
        return out

    @staticmethod
    def _looks_applied(page) -> bool:
        """Best-effort confirmation that the response actually went through."""
        try:
            loc = page.locator(SEL["already"])
            for i in range(min(loc.count(), 3)):
                try:
                    if loc.nth(i).is_visible(timeout=1200):
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        # «Написать сообщение» link appears in the after-apply block — the
        # most reliable sign on the current rabota.by markup.
        try:
            loc = page.locator(SEL["chat_link"])
            for i in range(min(loc.count(), 3)):
                try:
                    if loc.nth(i).is_visible(timeout=800):
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        try:
            loc = page.locator(SEL["response_success"])
            if loc.count() and loc.first.is_visible(timeout=500):
                return True
        except Exception:
            pass
        return False

    def _settled_looks_applied(self, page) -> bool:
        """Like _looks_applied but gives the page one more chance to update."""
        if self._looks_applied(page):
            return True
        time.sleep(1.5)
        return self._looks_applied(page)

    def _try_apply_once(self, page, letter: str, dry_run: bool) -> str:
        from playwright.sync_api import TimeoutError as PwTimeout

        blocker = self._detect_blockers(page)
        if blocker:
            return blocker
        if self._looks_archived(page):
            return "archived"
        if self._looks_applied(page):
            return "skipped"

        btn = page.locator(SEL["response_btn"]).first
        try:
            btn.wait_for(state="visible", timeout=10_000)
        except PwTimeout:
            # No «Откликнуться» button — the response may already have gone
            # through on a previous attempt (after-apply block is present).
            if self._settled_looks_applied(page):
                return "applied"
            return "error:no_response_button"
        if dry_run:
            return "dry_run"
        try:
            btn.click(timeout=5_000)
        except Exception as e:
            return f"error:click:{e}"
        # Cross-country dialog may pop before the response page opens.
        self._confirm_relocation_warning(page)

        # The response button navigates to a full-page form
        # (/applicant/vacancy_response); a second tab may also be used.
        # No fixed sleeps: wait_for_url/selector is the single gate (<=5s).
        try:
            if len(page.context.pages) > 1:
                page = page.context.pages[-1]
        except Exception:
            pass
        try:
            page.wait_for_url("**/applicant/vacancy_response**", timeout=12_000)
            return self._submit_response_form(page, letter, dry_run)
        except PwTimeout:
            pass
        form = page.locator(SEL["response_form"])
        try:
            form.wait_for(state="visible", timeout=5_000)
            return self._submit_response_form(page, letter, dry_run)
        except PwTimeout:
            pass

        blocker = self._detect_blockers(page)
        if blocker:
            return blocker
        # Legacy flow: in-page popup with a single letter textarea.
        area = page.locator(SEL["letter_area"]).first
        filled = False
        try:
            if area.count() and area.is_visible(timeout=4000):
                area.click()
                area.fill(letter)
                filled = True
        except Exception:
            pass
        self._last_letter_filled = filled
        submit = page.locator(SEL["submit_response"]).first
        submit_clicked = False
        try:
            if submit.count() and submit.is_visible(timeout=4000):
                submit.click()
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                submit_clicked = True
        except Exception:
            pass
        if not submit_clicked:
            # Some boards apply on the first click without a popup.
            if self._settled_looks_applied(page):
                return "applied"
            return "error:no_submit"
        # Confirm the response is recorded; otherwise let the caller retry.
        if self._settled_looks_applied(page):
            return "applied"
        return "error:unverified"

    def _submit_response_form(self, page, letter: str, dry_run: bool) -> str:
        """Full-page /applicant/vacancy_response: questions + letter + submit."""
        from playwright.sync_api import TimeoutError as PwTimeout

        blocker = self._detect_blockers(page)
        if blocker:
            return blocker
        self._confirm_relocation_warning(page)

        questions = page.locator(SEL["response_question_field"])
        if questions.count():
            answer = (self.settings.response_question_answer or "").strip()
            if not answer:
                return "need_manual"
            for i in range(questions.count()):
                questions.nth(i).fill(answer)

        # Optional cover letter via the toggle card.
        filled = False
        if letter:
            toggle = page.locator(SEL["letter_toggle"])
            try:
                if toggle.count() and toggle.first.is_visible(timeout=3000):
                    toggle.first.click(timeout=3000)
                    time.sleep(0.6)
            except Exception:
                pass
            try:
                for t in page.locator("textarea").all():
                    name = (t.get_attribute("name") or "")
                    if name.startswith("task_"):
                        continue
                    try:
                        if t.is_visible(timeout=3000):
                            t.click()
                            t.fill(letter)
                            filled = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        self._last_letter_filled = filled

        submit = page.locator(SEL["submit_response"]).first
        try:
            if not (submit.count() and submit.is_visible(timeout=8_000)):
                # No submit button: the response may still have gone through
                # instantly (button on vacancy page already reads "Вы откликнулись").
                if self._settled_looks_applied(page):
                    return "applied"
                return "error:no_submit"
            submit.click(timeout=4_000)
        except Exception:
            if self._settled_looks_applied(page):
                return "applied"
            return "error:no_submit"
        blocker = self._detect_blockers(page)
        if blocker:
            return blocker
        try:
            page.wait_for_selector(SEL["response_success"], timeout=8_000)
            return "applied"
        except PwTimeout:
            pass
        if self._settled_looks_applied(page):
            return "applied"
        return "error:unverified"

    @staticmethod
    def _company_from_page(page) -> str:
        """Best-effort employer name from HH vacancy page (empty if missing)."""
        try:
            loc = page.locator(SEL["company_name"]).first
            if loc.count() == 0:
                return ""
            text = (loc.inner_text(timeout=1500) or "").strip()
            return text[:120] if text else ""
        except Exception:
            return ""

    def _send_chat_followup(
        self,
        page,
        vac_url: str,
        message: str,
        limiter: RateLimiter,
        s: Settings,
        title: str = "",
    ) -> str:
        """Best-effort: open the employer chat and send the cover letter.

        Returns "chat_sent" / "chat_skipped". Never raises; the apply
        result already recorded — chat is a bonus, not a gate.

        Chatik flow (rabota.by 2026):
          «Чаты» button in header → conversation list → pick by vacancy title,
          or a direct «Написать сообщение» link on the vacancy page.
          Inside: «Добавить сопроводительное» → textarea → send button.
        """
        try:
            if not s.chat_after_apply:
                return "chat_skipped"
            message = (s.chat_message or message or "").strip()
            if not message:
                return "chat_skipped"

            # 1. Direct chat link on the vacancy page (after-apply block).
            self._goto(page, vac_url, limiter, expect=SEL["response_btn"])
            chat_url = ""
            link = page.locator(SEL["chat_link"]).first
            try:
                if link.count():
                    chat_url = (link.get_attribute("href") or "").strip()
            except Exception:
                chat_url = ""
            if chat_url:
                chat_url = urljoin(
                    f"{urlparse(vac_url).scheme}://{urlparse(vac_url).netloc}",
                    chat_url,
                )
                self._goto(page, chat_url, limiter, expect="")
                time.sleep(max(1.0, s.settle_ms / 1000.0))
                picked = self._pick_chatik_conversation(page, title)
                if not picked:
                    return "chat_skipped"
                return self._send_chatik_message(page, message, s)

            # 2. Header «Чаты» → chatik widget → reopen in a full tab.
            chat = self._open_chatik_tab(page, s)
            if chat is None:
                return "chat_skipped"
            picked = self._pick_chatik_conversation(chat, title)
            if not picked:
                return "chat_skipped"
            return self._send_chatik_message(chat, message, s)
        except Exception:
            return "chat_skipped"

    def _open_chatik_tab(self, page, s: Settings):
        """Click «Чаты» in the header and reopen the chatik widget in a tab."""
        from playwright.sync_api import TimeoutError as PwTimeout

        try:
            activator = page.locator(SEL["chatik_activator"]).first
            if not (activator.count() and activator.is_visible(timeout=3000)):
                return None
            activator.click(timeout=3000)
        except Exception:
            return None
        try:
            iframe = page.frame_locator(SEL["chatik_iframe"]).locator("body").first
            iframe.wait_for(state="attached", timeout=10_000)
        except PwTimeout:
            pass
        time.sleep(max(1.2, s.settle_ms / 1000.0))
        try:
            new_tab = page.locator(SEL["chatik_new_tab"]).first
            if not (new_tab.count() and new_tab.is_visible(timeout=3000)):
                return None
            with page.context.expect_page(timeout=10_000) as pinfo:
                new_tab.click(timeout=3000)
            chat = pinfo.value
            chat.wait_for_load_state("domcontentloaded")
            time.sleep(max(1.5, s.settle_ms / 1000.0))
            return chat
        except Exception:
            return None

    def _pick_chatik_conversation(self, page, title: str) -> bool:
        """Find and open the conversation whose subject matches the vacancy.

        Freshly-sent responses sit at the top of the list, so the first
        visible conversation is a fine fallback.
        """
        items = page.locator(SEL["chatik_conversation"])
        total = 0
        try:
            total = items.count()
        except Exception:
            total = 0
        if total == 0:
            items = page.locator('div[data-qa*="chatik"], li[data-qa*="chatik"]')
        hay = (title or "").casefold()
        for i in range(min(total, 60)):
            item = items.nth(i)
            try:
                if not item.is_visible(timeout=800):
                    continue
                text = (item.inner_text(timeout=800) or "").strip()
            except Exception:
                continue
            if hay and hay[:40] in text.casefold():
                item.click(timeout=2000)
                return True
        # Fallback 1: the freshest channel is ours (top of the list).
        for i in range(min(total, 60)):
            item = items.nth(i)
            try:
                if item.is_visible(timeout=500):
                    item.click(timeout=2000)
                    return True
            except Exception:
                continue
        # Fallback 2: a conversation may already be open.
        try:
            box = page.locator(SEL["chat_input"]).first
            if box.count() and box.is_visible(timeout=2000):
                return True
        except Exception:
            pass
        return False

    def _send_chatik_message(self, page, message: str, s: Settings) -> str:
        """Attach the cover letter via «Добавить сопроводительное» and send."""

        disabled = page.locator(SEL["chat_disabled"]).first
        try:
            if disabled.count() and disabled.is_visible(timeout=1200):
                return "chat_skipped"
        except Exception:
            pass

        # «Добавить сопроводительное» opens a composer popup with a textarea.
        attach = page.locator(SEL["chat_attach_letter"]).first
        try:
            if attach.count() and attach.is_visible(timeout=3000):
                attach.click(timeout=3000)
                time.sleep(max(0.8, s.settle_ms / 1000.0))
        except Exception:
            pass

        box = page.locator(SEL["chat_input"]).first
        try:
            if not (box.count() and box.is_visible(timeout=5_000)):
                return "chat_skipped"
            box.click(timeout=2_000)
            box.fill(message)
        except Exception:
            return "chat_skipped"

        send = page.locator(SEL["chat_send_btn"]).first
        try:
            if send.count() and send.is_visible(timeout=1500):
                send.click(timeout=3_000)
            else:
                page.keyboard.press("Enter")
        except Exception:
            try:
                page.keyboard.press("Enter")
            except Exception:
                return "chat_skipped"

        time.sleep(max(1.5, s.settle_ms / 1000.0))
        try:
            sent = page.locator(SEL["chat_new_message"]).last
            if sent.count() and sent.is_visible(timeout=2000):
                text = (sent.inner_text(timeout=1500) or "").strip()
                if text and message[:40] in text:
                    return "chat_sent"
        except Exception:
            pass
        return "chat_skipped"

    @staticmethod
    def _page_text(page) -> str:
        """Vacancy description only — not full body (similar vacancies / chrome)."""
        blocks: list[str] = []
        for sel in VACANCY_DESCRIPTION_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.count() == 0:
                    continue
                text = loc.inner_text(timeout=3_000) or ""
                if text.strip():
                    blocks.append(text)
            except Exception:
                continue
        body = ""
        try:
            body = page.inner_text("body", timeout=5_000) or ""
        except Exception:
            body = ""
        return pick_vacancy_description(blocks, body_fallback=body)


def safe_run(
    fn,
    uow: UnitOfWork,
    profile: str,
    alerts: AlertService | None = None,
    *,
    service: str = "hh",
) -> None:
    """Run job target; on crash keep DB progress and mark job_aborted."""
    try:
        fn()
    except Exception as e:
        tb = traceback.format_exc()[-2000:]
        short = user_facing_browser_error(e)
        uow.journal.log(
            profile,
            "job_aborted",
            short,
            level="error",
            payload={"tb": tb, "raw": str(e)[:2000]},
            service=service,
        )
        uow.journal.log(
            profile,
            "error",
            short,
            level="error",
            payload={"tb": tb},
            service=service,
        )
        # Prior per-item commits stay; only job status becomes error
        uow.jobs.set_status(profile, JobStatus.ERROR, short)
        notifier = alerts or get_alert_service()
        notifier.notify_error(
            profile,
            short,
            event="job_aborted",
            details={"note": "См. journal / логи сервера для traceback"},
        )
