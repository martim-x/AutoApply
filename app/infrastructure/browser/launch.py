"""Shared Chromium launch with sandbox-path sanitization and channel fallbacks."""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def sanitize_playwright_browsers_path() -> str | None:
    """
    Cursor agents often set PLAYWRIGHT_BROWSERS_PATH to a sandbox cache
    that may contain the wrong arch (mac-x64 on arm64) or be incomplete.
    Prefer the default user cache (~/Library/Caches/ms-playwright).
    """
    raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not raw:
        return None
    poisoned = (
        "cursor-sandbox-cache" in raw
        or "/T/cursor-sandbox" in raw
        or "sandbox-cache" in raw
    )
    if poisoned:
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        log.warning(
            "Unset poisoned PLAYWRIGHT_BROWSERS_PATH=%s (use default ms-playwright cache)",
            raw,
        )
        return raw
    return None


def _looks_like_headed_display_failure(text: str) -> bool:
    low = (text or "").lower()
    return (
        "missing x server" in low
        or "without having a xserver" in low
        or "platform failed to initialize" in low
        or ("headless" in low and "false" in low and "launch" in low)
    )


def user_facing_browser_error(exc: BaseException, *, limit: int = 240) -> str:
    """Short status/alert text — Playwright dumps must not flood the UI."""
    text = str(exc or "").strip() or type(exc).__name__
    low = text.lower()
    if _looks_like_headed_display_failure(text):
        return (
            "Chromium не запустился: нет дисплея (headed mode). "
            "В Docker/Railway нужен HEADLESS=true "
            "(или ENABLE_REMOTE_BROWSER=true)."
        )
    if "failed to launch chromium" in low:
        # Prefer first meaningful line; never return multi-line dumps.
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("failed to launch"):
                return (
                    "Chromium не запустился. "
                    "Проверьте HEADLESS / Playwright browsers."
                )[:limit]
            return line[:limit] if len(line) > limit else line
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def launch_chromium(playwright: Any, *, headless: bool = True):
    """
    Try bundled Playwright Chromium, then system Chrome / Chromium channels.
    Call sanitize_playwright_browsers_path() before first launch in-process.
    """
    sanitize_playwright_browsers_path()
    errors: list[str] = []
    attempts: list[dict[str, Any]] = [
        {"headless": headless},
        {"channel": "chrome", "headless": headless},
        {"channel": "chromium", "headless": headless},
    ]
    for kwargs in attempts:
        try:
            browser = playwright.chromium.launch(**kwargs)
            label = kwargs.get("channel") or "bundled-chromium"
            log.info("Chromium launched via %s (headless=%s)", label, headless)
            return browser
        except Exception as e:
            errors.append(f"{kwargs}: {e}")
            continue
    joined = "\n".join(errors[-3:])
    log.error("Chromium launch failed (headless=%s):\n%s", headless, joined)
    # Short exception for UI/alerts; full attempt dumps stay in the log above.
    if _looks_like_headed_display_failure(joined):
        raise RuntimeError(
            "Chromium не запустился: нет дисплея (headed mode). "
            "В Docker/Railway нужен HEADLESS=true "
            "(или ENABLE_REMOTE_BROWSER=true)."
        )
    raise RuntimeError(
        "Chromium не запустился. "
        "Проверьте HEADLESS / Playwright browsers "
        "(полный лог — в journal сервера)."
    )
