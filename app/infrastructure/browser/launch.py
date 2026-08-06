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
    hint = (
        "Run: unset PLAYWRIGHT_BROWSERS_PATH && poetry run playwright install chromium\n"
        "Or install Google Chrome for channel=chrome fallback."
    )
    raise RuntimeError(
        "Failed to launch Chromium.\n" + "\n".join(errors[-3:]) + "\n" + hint
    )
