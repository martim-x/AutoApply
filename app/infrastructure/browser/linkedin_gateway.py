"""
LinkedIn browser gateway (Playwright only — no official API tokens).

Separate from HH/rabota gateway so selectors/URL builders do not collide.
Conservative rate limits — LinkedIn may restrict accounts on aggressive use.
"""

from __future__ import annotations

import random
import re
import time
import traceback
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

from app.application.alerts import AlertService, get_alert_service
from app.domain.entities import LinkedInContact, LinkedInVacancyLink
from app.domain.enums import JobStatus
from app.domain.linkedin_profile import (
    LINKEDIN_LOGIN,
    LinkedInLaunchProfile,
    load_linkedin_launch,
)
from app.domain.parse_dedup import (
    is_duplicate_vacancy,
    next_old_streak,
    remember_vacancy,
    should_stop_old_streak,
)
from app.domain.ports import UnitOfWork
from app.infrastructure.browser.launch import launch_chromium, user_facing_browser_error
from app.infrastructure.browser.linkedin_selectors import LI_SEL
from app.infrastructure.settings import Settings


def linkedin_profile_id(url: str) -> str | None:
    m = re.search(r"/in/([^/?#]+)", url or "")
    return m.group(1) if m else None


def linkedin_job_id(url: str) -> str | None:
    m = re.search(r"/jobs/view/(\d+)", url or "")
    return m.group(1) if m else None


def _normalize_li_url(href: str, base: str = "https://www.linkedin.com") -> str:
    if not href:
        return ""
    full = urljoin(base, href.split("?")[0])
    # strip tracking
    parsed = urlparse(full)
    path = parsed.path.rstrip("/")
    if "/in/" in path:
        m = re.search(r"(/in/[^/]+)", path)
        if m:
            return f"https://www.linkedin.com{m.group(1)}/"
    if "/jobs/view/" in path:
        m = re.search(r"(/jobs/view/\d+)", path)
        if m:
            return f"https://www.linkedin.com{m.group(1)}/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


class LinkedInBrowserGateway:
    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        alerts: AlertService | None = None,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.alerts = alerts or get_alert_service(settings)

    def _log(
        self,
        profile: str,
        event: str,
        message: str = "",
        *,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.uow.journal.log(
            profile,
            event,
            message,
            level=level,
            payload=payload,
            service="linkedin",
        )

    def _profile(self) -> tuple[LinkedInLaunchProfile, list[str]]:
        lp, result = load_linkedin_launch(self.settings.linkedin_launch_path)
        return lp, result.notifications

    def _pause(self, base: float, jitter: float) -> None:
        spread = max(0.0, base * jitter)
        time.sleep(base + random.uniform(0, spread))

    def _sel_fail(self, profile: str, key: str, detail: str = "") -> None:
        msg = f"LinkedIn selector failed: {key}"
        if detail:
            msg = f"{msg} — {detail}"
        self._log(profile, "linkedin_selector_error", msg, level="error")

    def run_login(self, profile: str, stop_flag: Any) -> None:
        from playwright.sync_api import sync_playwright

        uow = self.uow
        uow.jobs.set_status(
            profile, JobStatus.LOGGING_IN, "Откройте браузер и войдите в LinkedIn"
        )
        self._log(profile, "linkedin_login_start", LINKEDIN_LOGIN)
        stop_flag.save_now = False

        with sync_playwright() as p:
            browser, context, sp = self._launch(p, profile)
            page = context.new_page()
            try:
                page.goto(LINKEDIN_LOGIN, wait_until="domcontentloaded")
                uow.jobs.set_status(
                    profile,
                    JobStatus.WAITING_USER,
                    "Войдите в LinkedIn, затем нажмите «Сессия сохранена»",
                )
                deadline = time.time() + 600
                while time.time() < deadline and not stop_flag.stopped:
                    if getattr(stop_flag, "save_now", False):
                        break
                    url = page.url or ""
                    if "/login" not in url and "/checkpoint" not in url:
                        page.wait_for_timeout(1200)
                        if "/login" not in (page.url or ""):
                            break
                    time.sleep(0.5)

                if stop_flag.stopped and not getattr(stop_flag, "save_now", False):
                    uow.jobs.set_status(profile, JobStatus.IDLE, "LinkedIn логин отменён")
                    return

                context.storage_state(path=str(sp))
                self._log(profile, "linkedin_session_saved", f"Сессия → {sp}")
                uow.jobs.set_status(
                    profile, JobStatus.DONE, f"LinkedIn сессия сохранена: {sp.name}"
                )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    def run_network(self, profile: str, stop_flag: Any) -> None:
        """People search → open profiles → Connect when available."""
        from playwright.sync_api import sync_playwright

        uow = self.uow
        s = self.settings
        launch, notes = self._profile()
        for n in notes:
            self._log(profile, "config_default", n, level="warning")

        sp = s.linkedin_state_path(profile)
        if not sp.exists():
            uow.jobs.set_status(
                profile, JobStatus.ERROR, "Нет LinkedIn сессии — сначала Login"
            )
            self._log(
                profile, "linkedin_network_abort", "нет storage_state", level="error"
            )
            return

        uow.jobs.set_status(
            profile,
            JobStatus.SEARCHING,
            f"LinkedIn networking… limit={launch.connect_limit}",
        )
        self._log(
            profile,
            "linkedin_network_start",
            f"locations={launch.locations} queries={launch.people_queries} "
            f"limit={launch.connect_limit} dry_run={launch.dry_run}",
        )

        connected = 0
        skipped = 0
        errors = 0

        with sync_playwright() as p:
            browser, context, _ = self._launch(p, profile)
            page = context.new_page()
            try:
                if self._blocked(page, profile):
                    return
                for query, location in launch.people_search_combos():
                    if stop_flag.stopped or connected >= launch.connect_limit:
                        break
                    keywords = f"{query} {location}".strip()
                    url = (
                        "https://www.linkedin.com/search/results/people/"
                        f"?keywords={quote_plus(keywords)}"
                    )
                    self._log(
                        profile, "linkedin_people_search", f"{keywords} → {url}"
                    )
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=s.navigation_timeout_ms)
                    except Exception as e:
                        self._log(
                            profile,
                            "linkedin_nav_error",
                            str(e),
                            level="error",
                        )
                        self._pause(launch.min_action_interval, launch.jitter)
                        continue

                    self._pause(launch.min_action_interval, launch.jitter)
                    if self._blocked(page, profile):
                        return

                    hrefs = self._collect_profile_links(page, profile)
                    hrefs = hrefs[: launch.max_profiles_per_query]
                    for href in hrefs:
                        if stop_flag.stopped or connected >= launch.connect_limit:
                            break
                        norm = _normalize_li_url(href)
                        if not linkedin_profile_id(norm):
                            continue
                        try:
                            status, err = self._connect_profile(
                                page,
                                profile,
                                norm,
                                query=f"{query}@{location}",
                                launch=launch,
                            )
                            # Persist each contact immediately
                            uow.linkedin_contacts.upsert(
                                LinkedInContact(
                                    profile=profile,
                                    url=norm,
                                    query=f"{query}@{location}",
                                    status=status,
                                    error=err,
                                )
                            )
                            if status == "connected":
                                connected += 1
                            elif status in ("pending", "skipped", "dry_run"):
                                skipped += 1
                            else:
                                errors += 1
                        except Exception as unit_exc:
                            errors += 1
                            self._log(
                                profile,
                                "unit_failed",
                                f"linkedin contact {norm}: {unit_exc}",
                                level="warn",
                            )
                            self.alerts.notify(
                                "unit_failed",
                                str(unit_exc)[:200],
                                profile=profile,
                                details={"url": norm},
                            )
                        self._pause(launch.after_connect_delay, launch.jitter)

                # refresh cookies
                try:
                    context.storage_state(path=str(sp))
                except Exception:
                    pass

                msg = (
                    f"LinkedIn network done: connected={connected} "
                    f"skipped={skipped} errors={errors}"
                )
                self._log(profile, "linkedin_network_done", msg)
                current = uow.jobs.get_status(profile)
                if current.status != JobStatus.WAITING_USER:
                    uow.jobs.set_status(profile, JobStatus.DONE, msg)
            except Exception as e:
                short = user_facing_browser_error(e)
                self._log(
                    profile,
                    "linkedin_network_error",
                    f"{short}\n{traceback.format_exc()[-1500:]}",
                    level="error",
                )
                uow.jobs.set_status(profile, JobStatus.ERROR, short)
                self.alerts.notify_error(
                    profile, short, event="linkedin_network_error"
                )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    def run_vacancies(self, profile: str, stop_flag: Any) -> None:
        """Vacancy search → scrape links/titles into linkedin_vacancies."""
        from playwright.sync_api import sync_playwright

        uow = self.uow
        s = self.settings
        launch, notes = self._profile()
        for n in notes:
            self._log(profile, "config_default", n, level="warning")

        sp = s.linkedin_state_path(profile)
        if not sp.exists():
            uow.jobs.set_status(
                profile, JobStatus.ERROR, "Нет LinkedIn сессии — сначала Login"
            )
            self._log(
                profile, "linkedin_vacancies_abort", "нет storage_state", level="error"
            )
            return

        uow.jobs.set_status(
            profile,
            JobStatus.SEARCHING,
            f"LinkedIn vacancies… limit={launch.vacancy_limit}",
        )
        saved = 0
        early_stop = bool(s.parse_early_stop_enabled)
        streak_stop = int(s.parse_old_streak_stop) if early_stop else 0
        known_urls = uow.linkedin_vacancies.known_urls(profile)
        known_ids: set[str] = {
            jid
            for u in known_urls
            if (jid := linkedin_job_id(u))
        }

        with sync_playwright() as p:
            browser, context, _ = self._launch(p, profile)
            page = context.new_page()
            try:
                if self._blocked(page, profile):
                    return
                for query, location in launch.vacancy_search_combos():
                    if stop_flag.stopped or saved >= launch.vacancy_limit:
                        break
                    url = (
                        "https://www.linkedin.com/jobs/search/"
                        f"?keywords={quote_plus(query)}"
                        f"&location={quote_plus(location)}"
                    )
                    # Date descending — required for safe old-streak early-stop
                    if early_stop:
                        url += "&sortBy=DD"
                    self._log(
                        profile, "linkedin_job_search", f"{query} @ {location}"
                    )
                    try:
                        page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=s.navigation_timeout_ms,
                        )
                    except Exception as e:
                        self._log(
                            profile, "linkedin_nav_error", str(e), level="error"
                        )
                        self._pause(launch.min_action_interval, launch.jitter)
                        continue

                    self._pause(launch.min_action_interval, launch.jitter)
                    if self._blocked(page, profile):
                        return

                    cards = self._collect_job_cards(page, profile)
                    old_streak = 0
                    for card in cards:
                        if stop_flag.stopped or saved >= launch.vacancy_limit:
                            break
                        link = card.get("url") or ""
                        jid = linkedin_job_id(link)
                        if not jid:
                            continue
                        title = card.get("title") or link
                        if is_duplicate_vacancy(
                            url=link,
                            vacancy_id=jid,
                            known_urls=known_urls,
                            known_ids=known_ids,
                        ):
                            old_streak = next_old_streak(old_streak, True)
                            self._log(
                                profile,
                                "filtered:duplicate",
                                title[:80],
                                payload={"url": link, "vacancy_id": jid, "source": "linkedin"},
                            )
                            if early_stop and should_stop_old_streak(
                                old_streak, streak_stop
                            ):
                                self._log(
                                    profile,
                                    "early_stop:old_streak",
                                    f"streak={old_streak} query={query!r}@{location}",
                                    payload={
                                        "streak": old_streak,
                                        "threshold": streak_stop,
                                        "query": f"{query}@{location}",
                                        "source": "linkedin",
                                    },
                                )
                                break
                            continue

                        old_streak = next_old_streak(old_streak, False)
                        try:
                            uow.linkedin_vacancies.upsert(
                                LinkedInVacancyLink(
                                    profile=profile,
                                    url=link,
                                    title=card.get("title") or "",
                                    company=card.get("company") or "",
                                    location=card.get("location") or location,
                                    query=f"{query}@{location}",
                                    source="linkedin",
                                )
                            )
                            remember_vacancy(
                                url=link,
                                vacancy_id=jid,
                                known_urls=known_urls,
                                known_ids=known_ids,
                            )
                            saved += 1
                        except Exception as unit_exc:
                            self._log(
                                profile,
                                "unit_failed",
                                f"linkedin vacancy {link}: {unit_exc}",
                                level="warn",
                            )
                            self.alerts.notify(
                                "unit_failed",
                                str(unit_exc)[:200],
                                profile=profile,
                                details={"url": link},
                            )
                            continue

                    self._pause(launch.min_action_interval, launch.jitter)

                try:
                    context.storage_state(path=str(sp))
                except Exception:
                    pass

                msg = f"LinkedIn vacancies saved={saved}"
                self._log(profile, "linkedin_vacancies_done", msg)
                current = uow.jobs.get_status(profile)
                if current.status != JobStatus.WAITING_USER:
                    uow.jobs.set_status(profile, JobStatus.DONE, msg)
            except Exception as e:
                short = user_facing_browser_error(e)
                self._log(
                    profile,
                    "linkedin_vacancies_error",
                    f"{short}\n{traceback.format_exc()[-1500:]}",
                    level="error",
                )
                uow.jobs.set_status(profile, JobStatus.ERROR, short)
                self.alerts.notify_error(
                    profile, short, event="linkedin_vacancies_error"
                )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    def _launch(self, p: Any, profile: str) -> tuple[Any, Any, Any]:
        s = self.settings
        sp = s.linkedin_state_path(profile)
        kwargs: dict[str, Any] = {
            "locale": "en-US",
            "viewport": {"width": 1280, "height": 900},
        }
        browser = launch_chromium(p, headless=s.effective_headless())
        if sp.exists():
            context = browser.new_context(storage_state=str(sp), **kwargs)
        else:
            context = browser.new_context(**kwargs)
        context.set_default_navigation_timeout(s.navigation_timeout_ms)
        context.set_default_timeout(s.content_timeout_ms)
        return browser, context, sp

    def _blocked(self, page: Any, profile: str) -> bool:
        """Detect login wall / checkpoint → alert + pause (WAITING_USER)."""
        try:
            url = page.url or ""
            if page.locator(LI_SEL["auth_wall"]).count() > 0 and "/feed" not in url:
                if "/login" in url or page.locator(LI_SEL["auth_wall"]).first.is_visible():
                    msg = "LinkedIn: нужна авторизация (login wall)"
                    self.uow.jobs.set_status(profile, JobStatus.WAITING_USER, msg)
                    self._log(
                        profile,
                        "linkedin_auth_wall",
                        url,
                        level="error",
                    )
                    self.alerts.notify_error(
                        profile, msg, event="linkedin_auth_wall", details={"url": url}
                    )
                    return True
            if page.locator(LI_SEL["checkpoint"]).count() > 0:
                msg = "LinkedIn checkpoint / verification — войдите вручную"
                self.uow.jobs.set_status(profile, JobStatus.WAITING_USER, msg)
                self._log(
                    profile, "linkedin_checkpoint", url, level="warn"
                )
                self.alerts.notify_captcha(
                    profile, msg, details={"url": url, "blocker": "linkedin_checkpoint"}
                )
                return True
        except Exception:
            pass
        return False

    def _collect_profile_links(self, page: Any, profile: str) -> list[str]:
        try:
            locs = page.locator(LI_SEL["profile_link"])
            n = min(locs.count(), 40)
            out: list[str] = []
            seen: set[str] = set()
            for i in range(n):
                href = locs.nth(i).get_attribute("href") or ""
                norm = _normalize_li_url(href)
                if not linkedin_profile_id(norm) or norm in seen:
                    continue
                seen.add(norm)
                out.append(norm)
            if not out:
                self._sel_fail(profile, "profile_link", "no results on SERP")
            return out
        except Exception as e:
            self._sel_fail(profile, "profile_link", str(e))
            return []

    def _collect_job_cards(self, page: Any, profile: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        try:
            locs = page.locator(LI_SEL["job_card_link"])
            n = min(locs.count(), 50)
            for i in range(n):
                el = locs.nth(i)
                href = el.get_attribute("href") or ""
                norm = _normalize_li_url(href)
                if not linkedin_job_id(norm) or norm in seen:
                    continue
                seen.add(norm)
                title = (el.inner_text() or "").strip()[:200]
                out.append({"url": norm, "title": title, "company": "", "location": ""})
            if not out:
                self._sel_fail(profile, "job_card_link", "no job cards")
        except Exception as e:
            self._sel_fail(profile, "job_card_link", str(e))
        return out

    def _connect_profile(
        self,
        page: Any,
        profile: str,
        url: str,
        *,
        query: str,
        launch: LinkedInLaunchProfile,
    ) -> tuple[str, str | None]:
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.settings.navigation_timeout_ms,
            )
            self._pause(launch.min_action_interval * 0.6, launch.jitter)
            if self._blocked(page, profile):
                return "error", "auth/checkpoint"

            # Already pending?
            try:
                if page.locator(LI_SEL["pending_btn"]).count() > 0:
                    if page.locator(LI_SEL["pending_btn"]).first.is_visible():
                        self._log(
                            profile, "linkedin_skip_pending", url
                        )
                        return "pending", None
            except Exception:
                pass

            connect = page.locator(LI_SEL["connect_btn"])
            if connect.count() == 0:
                # try More → Connect
                try:
                    more = page.locator(LI_SEL["more_btn"])
                    if more.count() > 0 and more.first.is_visible():
                        more.first.click(timeout=3000)
                        self._pause(1.2, launch.jitter)
                        connect = page.locator(LI_SEL["connect_btn"])
                except Exception:
                    pass

            if connect.count() == 0:
                self._log(
                    profile, "linkedin_skip_no_connect", url
                )
                return "skipped", "no Connect button"

            if launch.dry_run:
                self._log(
                    profile, "linkedin_dry_run_connect", url
                )
                return "dry_run", None

            connect.first.click(timeout=5000)
            self._pause(1.5, launch.jitter)
            # optional note modal → Send / Send without note
            try:
                send = page.locator(LI_SEL["send_now"])
                if send.count() > 0 and send.first.is_visible():
                    send.first.click(timeout=4000)
            except Exception as e:
                self._sel_fail(profile, "send_now", str(e))
            self._log(profile, "linkedin_connected", f"{url} ({query})")
            return "connected", None
        except Exception as e:
            self._log(
                profile, "linkedin_connect_error", f"{url}: {e}", level="error"
            )
            return "error", str(e)[:300]
