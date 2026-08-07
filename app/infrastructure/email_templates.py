"""HTML + plain-text email templates matching auto-apply-app light/dark palette."""

from __future__ import annotations

import html
from typing import Any, Literal

# Palette mirrored from app/interfaces/web/static/style.css (:root + [data-theme=dark]).
LIGHT = {
    "bg": "#f5f6f4",
    "panel": "#ffffff",
    "panel_soft": "#f4f5f3",
    "text": "#141816",
    "muted": "#5a635c",
    "accent": "#1f6b3a",
    "accent_soft": "#d8eedf",
    "line": "#d0d5cf",
    "danger": "#b32626",
    "danger_bg": "#f5dede",
    "warn": "#b8860b",
    "warn_bg": "#f7ecd2",
    "ok": "#1a7a38",
    "ok_bg": "#d8eedf",
    "pre_bg": "#f7f8f6",
    "pre_fg": "#1a211c",
}

DARK = {
    "bg": "#0a0c0a",
    "panel": "#1a1e1a",
    "panel_soft": "#141814",
    "text": "#e8ede7",
    "muted": "#8f9a90",
    "accent": "#3dcf6a",
    "accent_soft": "#163522",
    "line": "#2e352e",
    "danger": "#ef6b6b",
    "danger_bg": "#321818",
    "warn": "#f0c014",
    "warn_bg": "#2e2612",
    "ok": "#3dcf6a",
    "ok_bg": "#163522",
    "pre_bg": "#070907",
    "pre_fg": "#d7e0d9",
}

Kind = Literal["error", "captcha", "job", "notification"]

_KIND_META: dict[Kind, dict[str, str]] = {
    "error": {
        "badge": "Ошибка",
        "title_fallback": "Сбой в auto-apply-app",
        "accent_key": "danger",
        "bg_key": "danger_bg",
    },
    "captcha": {
        "badge": "Нужно действие",
        "title_fallback": "Требуется проверка",
        "accent_key": "warn",
        "bg_key": "warn_bg",
    },
    "job": {
        "badge": "Задача",
        "title_fallback": "Уведомление о задаче",
        "accent_key": "accent",
        "bg_key": "accent_soft",
    },
    "notification": {
        "badge": "Уведомление",
        "title_fallback": "Уведомление auto-apply-app",
        "accent_key": "accent",
        "bg_key": "accent_soft",
    },
}

_CAPTCHA_EVENTS = frozenset({"captcha", "need_manual", "linkedin_checkpoint"})
_JOB_EVENTS = frozenset(
    {
        "serp_fail",
        "unit_failed",
        "parse_fail",
        "linkedin_nav_error",
        "job_aborted",
        "search_abort",
    }
)


def escape_html(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def classify_alert_kind(event: str) -> Kind:
    ev = (event or "").strip().lower()
    if ev in _CAPTCHA_EVENTS or ev.startswith("captcha"):
        return "captcha"
    if ev in _JOB_EVENTS or ev.startswith("parse_"):
        return "job"
    if (
        ev in {"error", "browser_crash", "session_lost", "linkedin_auth_wall"}
        or ev.endswith("_error")
        or ev.startswith("error")
    ):
        return "error"
    return "notification"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _format_details(
    details: dict[str, Any] | None,
    *,
    max_items: int = 8,
    max_value: int = 280,
) -> list[tuple[str, str]]:
    """Sanitize detail rows for email (no full Playwright dumps)."""
    if not details:
        return []
    rows: list[tuple[str, str]] = []
    for key, value in list(details.items())[:max_items]:
        k = str(key)
        # Tracebacks / raw dumps → short preview only
        if k.lower() in {"tb", "traceback", "raw", "log", "dump"}:
            val = _truncate(str(value).replace("\r\n", "\n"), max_value)
        else:
            val = _truncate(str(value), max_value)
        if not val:
            continue
        rows.append((k, val))
    return rows


def render_plain_alert(
    *,
    kind: Kind,
    title: str,
    message: str,
    profile: str = "default",
    event: str = "",
    details: dict[str, Any] | None = None,
) -> str:
    meta = _KIND_META[kind]
    heading = (title or "").strip() or meta["title_fallback"]
    msg = _truncate(message, 400)
    lines = [
        "auto-apply-app",
        heading,
        "",
        f"Профиль: {profile}",
    ]
    if event:
        lines.append(f"Событие: {event}")
    if msg:
        lines.append(f"Сообщение: {msg}")
    rows = _format_details(details)
    if rows:
        lines.append("")
        lines.append("Подробности:")
        for k, v in rows:
            lines.append(f"  {k}: {v}")
    lines.extend(
        [
            "",
            "Откройте auto-apply-app, чтобы продолжить или исправить сессию.",
            "— auto-apply-app",
        ]
    )
    body = "\n".join(lines)
    return _truncate(body, 2000) if len(body) > 2000 else body


def render_html_alert(
    *,
    kind: Kind,
    title: str,
    message: str,
    profile: str = "default",
    event: str = "",
    details: dict[str, Any] | None = None,
) -> str:
    """
    Inline-friendly HTML with light defaults + prefers-color-scheme dark overrides.
    """
    L, D = LIGHT, DARK
    meta = _KIND_META[kind]
    heading = (title or "").strip() or meta["title_fallback"]
    msg = _truncate(message, 500)
    accent_l = L[meta["accent_key"]]  # type: ignore[literal-required]
    accent_d = D[meta["accent_key"]]  # type: ignore[literal-required]
    badge_bg_l = L[meta["bg_key"]]  # type: ignore[literal-required]
    badge_bg_d = D[meta["bg_key"]]  # type: ignore[literal-required]

    rows = _format_details(details)
    details_html = ""
    if rows:
        items = []
        for k, v in rows:
            items.append(
                "<tr>"
                f'<td style="padding:6px 10px;color:{L["muted"]};'
                f'font-size:12px;vertical-align:top;white-space:nowrap;">'
                f"{escape_html(k)}</td>"
                f'<td style="padding:6px 10px;color:{L["text"]};'
                f'font-size:12px;font-family:ui-monospace,Consolas,monospace;'
                f'word-break:break-word;">{escape_html(v)}</td>'
                "</tr>"
            )
        details_html = (
            '<div class="aa-details" style="margin-top:18px;">'
            f'<div style="font-size:11px;letter-spacing:0.06em;text-transform:uppercase;'
            f'color:{L["muted"]};margin-bottom:8px;">Подробности</div>'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'class="aa-details-table" style="background:{L["pre_bg"]};'
            f'border:1px solid {L["line"]};border-radius:8px;">'
            + "".join(items)
            + "</table></div>"
        )

    event_row = ""
    if event:
        event_row = (
            f'<tr><td style="padding:4px 0;color:{L["muted"]};font-size:13px;">'
            f'Событие</td>'
            f'<td style="padding:4px 0;color:{L["text"]};font-size:13px;'
            f'text-align:right;">{escape_html(event)}</td></tr>'
        )

    # Dark overrides via media query (supported by Apple Mail, Outlook.com, etc.)
    dark_css = f"""
@media (prefers-color-scheme: dark) {{
  .aa-body {{ background-color: {D["bg"]} !important; }}
  .aa-card {{ background-color: {D["panel"]} !important; border-color: {D["line"]} !important; }}
  .aa-brand, .aa-title, .aa-msg, .aa-meta td {{ color: {D["text"]} !important; }}
  .aa-muted, .aa-footer, .aa-details > div {{ color: {D["muted"]} !important; }}
  .aa-badge {{ background-color: {badge_bg_d} !important; color: {accent_d} !important; }}
  .aa-bar {{ background-color: {accent_d} !important; }}
  .aa-details-table {{ background-color: {D["pre_bg"]} !important; border-color: {D["line"]} !important; }}
  .aa-details-table td {{ color: {D["pre_fg"]} !important; }}
  .aa-details-table td:first-child {{ color: {D["muted"]} !important; }}
}}
""".strip()

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{escape_html(heading)}</title>
<style type="text/css">
{dark_css}
</style>
</head>
<body class="aa-body" style="margin:0;padding:0;background-color:{L["bg"]};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="aa-body"
         style="background-color:{L["bg"]};padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0" class="aa-card"
               style="max-width:560px;width:100%;background-color:{L["panel"]};
               border:1px solid {L["line"]};border-radius:12px;overflow:hidden;">
          <tr>
            <td class="aa-bar" style="height:4px;background-color:{accent_l};font-size:0;line-height:0;">&nbsp;</td>
          </tr>
          <tr>
            <td style="padding:22px 24px 8px 24px;">
              <div class="aa-brand" style="font-family:Georgia,'Source Serif 4',serif;
                   font-size:22px;font-weight:600;color:{L["text"]};letter-spacing:-0.02em;">
                auto-apply-app
              </div>
              <div class="aa-muted" style="margin-top:4px;font-family:'Segoe UI',Helvetica,Arial,sans-serif;
                   font-size:12px;color:{L["muted"]};">
                Уведомления приложения
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 20px 24px;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
              <span class="aa-badge" style="display:inline-block;padding:4px 10px;border-radius:6px;
                    background-color:{badge_bg_l};color:{accent_l};font-size:11px;
                    font-weight:600;letter-spacing:0.04em;text-transform:uppercase;">
                {escape_html(meta["badge"])}
              </span>
              <h1 class="aa-title" style="margin:14px 0 10px 0;font-size:20px;line-height:1.3;
                  font-weight:600;color:{L["text"]};">{escape_html(heading)}</h1>
              <p class="aa-msg" style="margin:0 0 16px 0;font-size:15px;line-height:1.5;
                 color:{L["text"]};">{escape_html(msg) if msg else "—"}</p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="aa-meta"
                     style="border-top:1px solid {L["line"]};padding-top:12px;">
                <tr>
                  <td style="padding:4px 0;color:{L["muted"]};font-size:13px;">Профиль</td>
                  <td style="padding:4px 0;color:{L["text"]};font-size:13px;text-align:right;">
                    {escape_html(profile)}
                  </td>
                </tr>
                {event_row}
              </table>
              {details_html}
            </td>
          </tr>
          <tr>
            <td class="aa-footer" style="padding:14px 24px 20px 24px;border-top:1px solid {L["line"]};
                font-family:'Segoe UI',Helvetica,Arial,sans-serif;font-size:12px;line-height:1.45;
                color:{L["muted"]};">
              Откройте auto-apply-app, чтобы продолжить или исправить сессию.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def render_alert_email(
    *,
    event: str,
    message: str,
    profile: str = "default",
    details: dict[str, Any] | None = None,
    title: str | None = None,
    kind: Kind | None = None,
) -> tuple[str, str]:
    """
    Build (plain_text, html) for an alert.
    Title defaults to a short message / kind fallback.
    """
    resolved_kind = kind or classify_alert_kind(event)
    heading = (title or "").strip()
    if not heading:
        heading = _truncate(message, 80) or _KIND_META[resolved_kind]["title_fallback"]
    plain = render_plain_alert(
        kind=resolved_kind,
        title=heading,
        message=message,
        profile=profile,
        event=event,
        details=details,
    )
    html_body = render_html_alert(
        kind=resolved_kind,
        title=heading,
        message=message,
        profile=profile,
        event=event,
        details=details,
    )
    return plain, html_body
