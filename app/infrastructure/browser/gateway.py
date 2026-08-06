"""Playwright browser gateway implementing BrowserGateway port."""

from __future__ import annotations

import re
import time
import traceback
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

from app.application.letter import RateLimiter, load_letter, render_letter
from app.domain.categorize import categorize_vacancy
from app.domain.entities import Application, Vacancy
from app.domain.enums import ApplyStatus, FitCategory, JobStatus
from app.domain.filters import evaluate_vacancy
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.launch import launch_chromium
from app.infrastructure.browser.selectors import SEL
from app.infrastructure.settings import Settings


def vacancy_id_from_url(url: str) -> str | None:
    m = re.search(r"/vacancy/(\d+)", url)
    return m.group(1) if m else None


class PlaywrightBrowserGateway:
    def __init__(self, uow: UnitOfWork, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    def run_login(self, profile: str, stop_flag: Any) -> None:
        from playwright.sync_api import sync_playwright

        s = self.settings
        uow = self.uow
        uow.jobs.set_status(
            profile, JobStatus.LOGGING_IN, "Откройте браузер и войдите на rabota.by"
        )
        uow.journal.log(profile, "login_start", "Старт логина")
        setattr(stop_flag, "save_now", False)

        with sync_playwright() as p:
            browser, context, sp = self._launch(p, profile)
            page = context.new_page()
            try:
                page.goto(f"{s.base_url}/account/login", wait_until="domcontentloaded")
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
        sp = s.state_path(profile)
        if not sp.exists():
            uow.jobs.set_status(profile, JobStatus.ERROR, "Нет сессии — сначала Login")
            uow.journal.log(profile, "search_abort", "нет storage_state", level="error")
            return

        uow.jobs.set_status(profile, JobStatus.SEARCHING, "Поиск вакансий…")
        queries = s.search_list()
        uow.journal.log(profile, "search_start", f"queries={queries}")
        limiter = RateLimiter(s.min_action_interval, s.jitter)
        found = 0
        kept = 0

        with sync_playwright() as p:
            browser, context, spath = self._launch(p, profile)
            page = context.new_page()
            try:
                seen: set[str] = set()
                for qi, query in enumerate(queries):
                    if stop_flag.stopped:
                        break
                    serp = self._serp_url(query)
                    uow.journal.log(profile, "serp", f"[{qi+1}/{len(queries)}] {query!r}")
                    uow.jobs.set_status(
                        profile,
                        JobStatus.SEARCHING,
                        f"Поиск: {query} ({qi+1}/{len(queries)})",
                        stats=uow.stats(profile),
                    )
                    if not self._goto(page, serp, limiter, expect=SEL["vacancy_link"]):
                        uow.journal.log(profile, "serp_fail", query, level="warn")
                        continue

                    blocker = self._detect_blockers(page)
                    if blocker:
                        uow.jobs.set_status(
                            profile, JobStatus.WAITING_USER, f"Блокер: {blocker}"
                        )
                        uow.journal.log(profile, blocker, "нужен ручной вход", level="warn")
                        return

                    for item in self._collect_links(page, limit=max(s.apply_limit * 2, 50)):
                        if stop_flag.stopped or kept >= s.apply_limit:
                            break
                        path = urlparse(item["url"]).path
                        if path in seen:
                            continue
                        seen.add(path)
                        found += 1
                        url, title = item["url"], item["title"] or item["url"]

                        pre = evaluate_vacancy(
                            url, title, "",
                            require_remote_or_hybrid=False,
                            skip_gov=s.skip_gov,
                            require_python_keywords=False,
                        )
                        if not pre.ok:
                            uow.vacancies.upsert(
                                Vacancy(
                                    profile=profile,
                                    url=url,
                                    vacancy_id=vacancy_id_from_url(url),
                                    title=title,
                                    query=query,
                                    serp_url=serp,
                                    category=FitCategory.LOW,
                                    filter_status=pre.status,
                                    apply_status=ApplyStatus.SKIPPED,
                                )
                            )
                            continue

                        loaded = self._goto(
                            page, url, limiter, expect=SEL["response_btn"]
                        )
                        page_text = self._page_text(page) if loaded else ""
                        decision = evaluate_vacancy(
                            url, title, page_text,
                            require_remote_or_hybrid=s.require_remote_or_hybrid,
                            skip_gov=s.skip_gov,
                            require_python_keywords=s.require_python_keywords,
                        )
                        cat = categorize_vacancy(title, page_text, url=url)
                        ok = decision.ok
                        uow.vacancies.upsert(
                            Vacancy(
                                profile=profile,
                                url=url,
                                vacancy_id=vacancy_id_from_url(url),
                                title=title,
                                description=page_text[:5000],
                                query=query,
                                serp_url=serp,
                                category=cat.category,
                                score=cat.score,
                                category_reason=cat.explanation or cat.reason,
                                filter_status="ok" if ok else decision.status,
                                apply_status=ApplyStatus.QUEUED if ok else ApplyStatus.SKIPPED,
                            )
                        )
                        if ok:
                            kept += 1
                            uow.journal.log(
                                profile,
                                "queued",
                                f"[{cat.category.value}/{cat.score}] {title[:70]}",
                            )
                        else:
                            uow.journal.log(profile, decision.status, title[:80])

                        try:
                            self._goto(page, serp, limiter, expect=SEL["vacancy_link"])
                        except Exception:
                            pass

                    if kept >= s.apply_limit:
                        break

                try:
                    context.storage_state(path=str(spath))
                    uow.profiles.save_session(profile, spath)
                except Exception:
                    pass

                stats = uow.stats(profile)
                msg = f"Найдено {found}, в очереди подходящих: {kept}"
                status = JobStatus.IDLE if stop_flag.stopped else JobStatus.DONE
                if stop_flag.stopped:
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
        if not s.state_path(profile).exists():
            uow.jobs.set_status(profile, JobStatus.ERROR, "Нет сессии — сначала Login")
            return

        ok, reason = self._under_quota(profile)
        if not ok:
            uow.jobs.set_status(profile, JobStatus.ERROR, reason)
            return

        queue = uow.vacancies.next_queued(profile, limit=s.apply_limit)
        if not queue:
            uow.jobs.set_status(profile, JobStatus.DONE, "Очередь пуста — сначала Search")
            return

        template = load_letter(s.letter_path)
        limiter = RateLimiter(s.min_action_interval, s.jitter)
        uow.jobs.set_status(
            profile,
            JobStatus.APPLYING,
            f"Отклик: {len(queue)} в очереди (HIGH→MEDIUM→LOW)",
            stats=uow.stats(profile),
        )
        uow.journal.log(profile, "apply_start", f"queue={len(queue)}")
        applied = 0

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
                        stats=uow.stats(profile),
                    )

                    if uow.applications.already_applied(profile, vac.url):
                        uow.vacancies.set_apply_status(vac.id, "skipped")
                        continue

                    t0 = time.time()
                    loaded = self._goto(
                        page, vac.url, limiter, expect=SEL["response_btn"]
                    )
                    if not loaded:
                        status, attempts = "load_fail", 1
                    else:
                        page_text = self._page_text(page)
                        decision = evaluate_vacancy(
                            vac.url, title, page_text,
                            require_remote_or_hybrid=s.require_remote_or_hybrid,
                            skip_gov=s.skip_gov,
                            require_python_keywords=s.require_python_keywords,
                        )
                        if not decision.ok:
                            status, attempts = decision.status, 0
                        else:
                            letter = render_letter(template, vacancy_name=title)
                            status = "error:unknown"
                            attempts = 0
                            for attempts in range(1, s.apply_retries + 1):
                                status = self._try_apply_once(page, letter, s.dry_run)
                                if status in (
                                    "applied", "skipped", "dry_run",
                                    "need_manual", "captcha",
                                ):
                                    break
                                if attempts < s.apply_retries:
                                    self._goto(
                                        page, vac.url, limiter, expect=SEL["response_btn"]
                                    )
                                    time.sleep(s.load_retry_delay)

                    duration_ms = int((time.time() - t0) * 1000)
                    uow.applications.record(
                        Application(
                            profile=profile,
                            vacancy_url=vac.url,
                            vacancy_id=vacancy_id_from_url(vac.url),
                            title=title,
                            category=cat,
                            status=status,
                            attempt=attempts,
                            error=None if not str(status).startswith("error:") else status,
                            dry_run=s.dry_run,
                            duration_ms=duration_ms,
                        )
                    )

                    if status in ("applied", "dry_run"):
                        uow.vacancies.set_apply_status(
                            vac.id, "applied" if status == "applied" else "dry_run"
                        )
                        applied += 1
                        limiter.wait(extra=s.after_apply_delay - s.min_action_interval)
                    elif status.startswith("filtered:") or status == "skipped":
                        uow.vacancies.set_apply_status(vac.id, "skipped")
                    elif status in ("need_manual", "captcha"):
                        uow.vacancies.set_apply_status(vac.id, "queued")
                        uow.jobs.set_status(
                            profile, JobStatus.WAITING_USER, f"Нужен человек: {status}"
                        )
                        uow.journal.log(profile, status, title[:80], level="warn")
                        break
                    else:
                        uow.vacancies.set_apply_status(vac.id, "failed")

                    uow.journal.log(profile, status, f"[{cat}] {title[:70]}")

                try:
                    context.storage_state(path=str(spath))
                    uow.profiles.save_session(profile, spath)
                except Exception:
                    pass

                stats = uow.stats(profile)
                current = uow.jobs.get_status(profile)
                if stop_flag.stopped:
                    uow.jobs.set_status(
                        profile, JobStatus.IDLE,
                        f"Остановлено. Откликов: {applied}", stats=stats,
                    )
                elif current.status != JobStatus.WAITING_USER:
                    uow.jobs.set_status(
                        profile, JobStatus.DONE,
                        f"Готово. Откликов за прогон: {applied}", stats=stats,
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
        kwargs: dict[str, Any] = {
            "locale": "ru-RU",
            "viewport": {"width": 1280, "height": 900},
        }
        browser = launch_chromium(p, headless=s.headless)
        if sp.exists():
            context = browser.new_context(storage_state=str(sp), **kwargs)
        else:
            context = browser.new_context(**kwargs)
        context.set_default_navigation_timeout(s.navigation_timeout_ms)
        context.set_default_timeout(s.content_timeout_ms)
        return browser, context, sp

    def _serp_url(self, query: str) -> str:
        s = self.settings
        url = f"{s.base_url}/search/vacancy?text={quote_plus(query)}&items_on_page=50"
        if s.search_area:
            url += f"&area={s.search_area}"
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

    def _try_apply_once(self, page, letter: str, dry_run: bool) -> str:
        from playwright.sync_api import TimeoutError as PwTimeout

        blocker = self._detect_blockers(page)
        if blocker:
            return blocker
        try:
            loc = page.locator(SEL["already"])
            for i in range(min(loc.count(), 3)):
                try:
                    if loc.nth(i).is_visible(timeout=400):
                        return "skipped"
                except Exception:
                    continue
        except Exception:
            pass

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
        page.wait_for_timeout(900)
        blocker = self._detect_blockers(page)
        if blocker:
            return blocker
        area = page.locator(SEL["letter_area"]).first
        try:
            if area.count() and area.is_visible(timeout=2500):
                area.click()
                area.fill(letter)
                page.wait_for_timeout(350)
        except Exception:
            pass
        submit = page.locator(SEL["submit_response"]).first
        try:
            if submit.count() and submit.is_visible(timeout=2500):
                submit.click()
                page.wait_for_timeout(1400)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return "applied"
        except Exception:
            pass
        page.wait_for_timeout(800)
        return "applied"

    @staticmethod
    def _page_text(page) -> str:
        try:
            return (page.inner_text("body", timeout=5_000) or "")[:80_000]
        except Exception:
            return ""


def safe_run(fn, uow: UnitOfWork, profile: str) -> None:
    try:
        fn()
    except Exception as e:
        uow.journal.log(
            profile, "error", str(e), level="error",
            payload={"tb": traceback.format_exc()[-2000:]},
        )
        uow.jobs.set_status(profile, JobStatus.ERROR, str(e))
