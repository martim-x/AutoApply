"""HH-platform (rabota.by) CSS selectors."""

# Vacancy body only — avoid SERP chrome / «похожие вакансии» polluting keywords.
VACANCY_DESCRIPTION_SELECTORS: tuple[str, ...] = (
    '[data-qa="vacancy-description"]',
    '[data-qa="vacancy__description"]',
    'div[data-qa="vacancy-description"]',
    ".vacancy-description",
    '[data-qa="vacancy-description"] .g-user-content',
    ".g-user-content.vacancy-description",
    "#vacancy-description",
)

SEL = {
    "vacancy_link": (
        'a[data-qa="serp-item__title"],'
        'a[data-qa="vacancy-serp__vacancy-title"],'
        'a[href*="/vacancy/"]'
    ),
    "response_btn": (
        '[data-qa="vacancy-serp__vacancy_response"],'
        '[data-qa="vacancy-response-link-top"],'
        '[data-qa="vacancy__response-button"],'
        'button:has-text("Откликнуться"),'
        'a:has-text("Откликнуться")'
    ),
    "vacancy_description": ",".join(VACANCY_DESCRIPTION_SELECTORS),
    "company_name": (
        '[data-qa="vacancy-company-name"],'
        'a[data-qa="vacancy-company-name"],'
        '[data-qa="vacancy__company-name"],'
        '.vacancy-company-name'
    ),
    "letter_area": (
        'textarea[data-qa="vacancy-response-popup-form-letter-input"],'
        'textarea[data-qa="textarea-letter"],'
        'textarea[name="letter"],'
        "textarea"
    ),
    # Full-page response form (new rabota.by flow): /applicant/vacancy_response
    "response_form": 'form[name="vacancy_response"]',
    "response_question": '[data-qa="task-question"]',
    "response_question_field": 'textarea[name^="task_"]',
    "letter_toggle": '[data-qa="vacancy-response-letter-toggle"]',
    "response_success": "text=Отклик отправлен",
    # Cross-country response warning dialog (e.g. hh.ru vacancy on rabota.by)
    "relocation_confirm": '[data-qa="relocation-warning-confirm"]',
    "submit_response": (
        '[data-qa="vacancy-response-submit-popup"],'
        '[data-qa="vacancy-response-letter-submit"],'
        'button:has-text("Отправить"),'
        'button:has-text("Откликнуться")'
    ),
    "already": (
        'button:has-text("Вы откликнулись"),'
        'span:has-text("Вы откликнулись"),'
        'a:has-text("Вы откликнулись"),'
        '[data-qa="vacancy-serp__vacancy_response"]:has-text("Откликнулись")'
    ),
    "captcha": (
        '[data-qa="account-captcha-picture"],'
        'iframe[src*="captcha"],'
        ".captcha"
    ),
}
