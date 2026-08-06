"""
Centralized LinkedIn DOM selectors (fragile — UI changes break automation).

When a selector fails, gateway logs a clear journal error with the selector key.
Keep human-like delays; LinkedIn aggressively rate-limits / restricts accounts.
"""

from __future__ import annotations

# People search result profile links
LI_SEL = {
    "profile_link": 'a[href*="/in/"]',
    "connect_btn": (
        'button:has-text("Connect"), '
        'button:has-text("Установить контакт"), '
        'button:has-text("Connect"), '
        'button[aria-label*="Invite" i], '
        'button[aria-label*="Connect" i], '
        'button[aria-label*="Установить контакт" i]'
    ),
    "pending_btn": (
        'button:has-text("Pending"), '
        'button:has-text("Ожидание"), '
        'button:has-text("Sent"), '
        'button[aria-label*="Pending" i], '
        'button[aria-label*="Ожидание" i]'
    ),
    "more_btn": (
        'button[aria-label*="More" i], '
        'button[aria-label*="Дополнительно" i], '
        'button:has-text("More")'
    ),
    "send_now": (
        'button:has-text("Send"), '
        'button:has-text("Send now"), '
        'button:has-text("Отправить"), '
        'button[aria-label*="Send" i]'
    ),
    "dismiss_modal": (
        'button[aria-label*="Dismiss" i], '
        'button[aria-label*="Закрыть" i], '
        'button:has-text("Cancel"), '
        'button:has-text("Отмена")'
    ),
    "auth_wall": (
        'input[name="session_key"], '
        'input#username, '
        'form.login__form, '
        '[data-test-id="sign-in-form"]'
    ),
    "checkpoint": (
        'input[name="pin"], '
        '#input__email_verification_pin, '
        '[id*="challenge"]'
    ),
    # Jobs
    "job_card_link": 'a[href*="/jobs/view/"]',
    "job_title": (
        ".job-card-list__title, "
        ".base-search-card__title, "
        "h3.base-search-card__title, "
        "a.job-card-list__title-link"
    ),
    "job_company": (
        ".job-card-container__primary-description, "
        ".base-search-card__subtitle, "
        "h4.base-search-card__subtitle"
    ),
    "job_location": (
        ".job-card-container__metadata-item, "
        ".job-search-card__location, "
        ".base-search-card__metadata"
    ),
}
