"""Shared Chromium launch with sandbox-path sanitization and channel fallbacks."""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# Masks the "controlled by automation" flag bots rely on (also drops the
# "Chrome is being controlled by automated test software" infobar).
ANTI_AUTOMATION_ARGS: tuple[str, ...] = (
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-sandbox",
    "--disable-dev-shm-usage",
)

DEFAULT_VIEWPORT: dict[str, int] = {"width": 1280, "height": 900}


def browser_context_kwargs(
    settings: Any,
    *,
    locale: str = "ru-RU",
    viewport: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Shared new_context kwargs: locale, viewport, color scheme, UA + timezone."""
    kwargs: dict[str, Any] = {
        "locale": locale,
        "viewport": viewport or DEFAULT_VIEWPORT,
        "color_scheme": "light",
        "extra_http_headers": {"Accept-Language": locale},
    }
    ua = (getattr(settings, "browser_user_agent", "") or "").strip()
    if ua:
        kwargs["user_agent"] = ua
    tz = (getattr(settings, "browser_timezone", "") or "").strip()
    if tz:
        kwargs["timezone_id"] = tz
    return kwargs


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
        {
            "headless": headless,
            "args": list(ANTI_AUTOMATION_ARGS),
            "ignore_default_args": ["--enable-automation"],
        },
        {
            "channel": "chrome",
            "headless": headless,
            "args": list(ANTI_AUTOMATION_ARGS),
            "ignore_default_args": ["--enable-automation"],
        },
        {
            "channel": "chromium",
            "headless": headless,
            "args": list(ANTI_AUTOMATION_ARGS),
            "ignore_default_args": ["--enable-automation"],
        },
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
