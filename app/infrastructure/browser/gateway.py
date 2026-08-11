"""Playwright browser gateway implementing BrowserGateway port."""

from __future__ import annotations

import re
import time
import traceback
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

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
                            for attempts in range(1, s.apply_retries + 1):
                                status = self._try_apply_once(page, letter, dry_run)
                                if status == "error:unverified":
                                    saw_unverified = True
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
                            if saw_unverified and status == "skipped":
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
                                    details={"url": vac.url, "status": status},
                                )

                        processed += 1
                        uow.journal.log(profile, status, f"[{cat}] {title[:70]}")
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

    def _goto(self, page, url: str, limiter: RateLimiter, *, expect: str | None = None) -> bool:
        from playwright.sync_api import TimeoutError as PwTimeout

        s = self.settings
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
        return False

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
            btn.wait_for(state="visible", timeout=8_000)
        except PwTimeout:
            return "error:no_response_button"
        if dry_run:
            return "dry_run"
        try:
            btn.click(timeout=5_000)
        except Exception as e:
            return f"error:click:{e}"

        # The response button navigates to a full-page form
        # (/applicant/vacancy_response); a second tab may also be used.
        # No fixed sleeps: wait_for_url/selector is the single gate (<=5s).
        try:
            if len(page.context.pages) > 1:
                page = page.context.pages[-1]
        except Exception:
            pass
        try:
            page.wait_for_url("**/applicant/vacancy_response**", timeout=5_000)
            return self._submit_response_form(page, letter, dry_run)
        except PwTimeout:
            pass
        form = page.locator(SEL["response_form"])
        try:
            form.wait_for(state="visible", timeout=3_000)
            return self._submit_response_form(page, letter, dry_run)
        except PwTimeout:
            pass

        blocker = self._detect_blockers(page)
        if blocker:
            return blocker
        # Legacy flow: in-page popup with a single letter textarea.
        area = page.locator(SEL["letter_area"]).first
        try:
            if area.count() and area.is_visible(timeout=2000):
                area.click()
                area.fill(letter)
        except Exception:
            pass
        submit = page.locator(SEL["submit_response"]).first
        submit_clicked = False
        try:
            if submit.count() and submit.is_visible(timeout=2000):
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
            if self._looks_applied(page):
                return "applied"
            return "error:no_submit"
        # Confirm the response is recorded; otherwise let the caller retry.
        if self._looks_applied(page):
            return "applied"
        return "error:unverified"

    def _submit_response_form(self, page, letter: str, dry_run: bool) -> str:
        """Full-page /applicant/vacancy_response: questions + letter + submit."""
        from playwright.sync_api import TimeoutError as PwTimeout

        blocker = self._detect_blockers(page)
        if blocker:
            return blocker

        questions = page.locator(SEL["response_question_field"])
        if questions.count():
            answer = (self.settings.response_question_answer or "").strip()
            if not answer:
                return "need_manual"
            for i in range(questions.count()):
                questions.nth(i).fill(answer)

        # Optional cover letter via the toggle card.
        if letter:
            toggle = page.locator(SEL["letter_toggle"])
            try:
                if toggle.count() and toggle.first.is_visible(timeout=1500):
                    toggle.first.click(timeout=2500)
            except Exception:
                pass
            try:
                for t in page.locator("textarea").all():
                    name = (t.get_attribute("name") or "")
                    if name.startswith("task_"):
                        continue
                    try:
                        if t.is_visible(timeout=1500):
                            t.click()
                            t.fill(letter)
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        submit = page.locator(SEL["submit_response"]).first
        try:
            if not (submit.count() and submit.is_visible(timeout=4_000)):
                return "error:no_submit"
            submit.click(timeout=4_000)
        except Exception:
            return "error:no_submit"
        blocker = self._detect_blockers(page)
        if blocker:
            return blocker
        try:
            page.wait_for_selector(SEL["response_success"], timeout=5_000)
            return "applied"
        except PwTimeout:
            pass
        if self._looks_applied(page):
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
