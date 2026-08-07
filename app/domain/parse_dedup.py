"""Duplicate detection + SERP early-stop helpers (newest→older, page-aware)."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def next_old_streak(streak: int, is_old: bool) -> int:
    """
    Track consecutive already-known vacancies.
    New vacancy → reset to 0; old/duplicate → increment.
    """
    if is_old:
        return max(0, int(streak)) + 1
    return 0


def should_stop_old_streak(streak: int, threshold: int) -> bool:
    """True when streak of old vacancies reached configured N (0 = disabled)."""
    n = int(threshold)
    if n <= 0:
        return False
    return int(streak) >= n


def next_dup_page_streak(streak: int, page_all_duplicates: bool) -> int:
    """
    Track consecutive SERP pages that contain only already-known vacancies.
    A page with any new listing resets the streak.
    """
    if page_all_duplicates:
        return max(0, int(streak)) + 1
    return 0


def should_stop_dup_pages(streak: int, threshold: int) -> bool:
    """True when consecutive fully-duplicate pages reached N (0 = disabled)."""
    return should_stop_old_streak(streak, threshold)


def serp_page_all_duplicates(dup_flags: list[bool]) -> bool:
    """True when the page has listings and every one is already known."""
    return bool(dup_flags) and all(dup_flags)


def serp_page_boundary_duplicates(dup_flags: list[bool]) -> bool:
    """
    True when first and last listing on the page are both known.
    Used as a soft signal that the window is in an already-seen region
    (still process the page for any new items in the middle).
    """
    return len(dup_flags) >= 2 and bool(dup_flags[0]) and bool(dup_flags[-1])


def hh_vacancy_id(url: str) -> str | None:
    m = re.search(r"/vacancy/(\d+)", url or "")
    return m.group(1) if m else None


def linkedin_job_id(url: str) -> str | None:
    m = re.search(r"/jobs/view/(\d+)", url or "")
    return m.group(1) if m else None


def canonical_vacancy_url(url: str) -> str:
    """Strip query/fragment; keep scheme+host+path for identity."""
    if not url:
        return ""
    raw = url.split("#", 1)[0].split("?", 1)[0].strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/")
    path = parsed.path.rstrip("/") or ""
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def is_duplicate_vacancy(
    *,
    url: str,
    vacancy_id: str | None,
    known_urls: set[str],
    known_ids: set[str],
) -> bool:
    """
    True if URL / canonical link / vacancy_id already known for the profile.
    """
    canon = canonical_vacancy_url(url)
    if canon and canon in known_urls:
        return True
    if url and url in known_urls:
        return True
    vid = (vacancy_id or "").strip()
    if not vid:
        vid = hh_vacancy_id(url) or linkedin_job_id(url) or ""
    if vid and vid in known_ids:
        return True
    return False


def remember_vacancy(
    *,
    url: str,
    vacancy_id: str | None,
    known_urls: set[str],
    known_ids: set[str],
) -> None:
    """Add identity keys to in-run known sets after inserting a vacancy."""
    canon = canonical_vacancy_url(url)
    if canon:
        known_urls.add(canon)
    if url:
        known_urls.add(url)
    vid = (vacancy_id or "").strip() or hh_vacancy_id(url) or linkedin_job_id(url)
    if vid:
        known_ids.add(vid)
