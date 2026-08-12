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
    "letter_toggle": (
        '[data-qa="vacancy-response-letter-toggle"],'
        '[data-qa*="vacancy-response-letter"],'
        'button:has-text("Добавить сопроводительное"),'
        'button:has-text("Сопроводительное письмо"),'
        'text=Добавить сопроводительное'
    ),
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
    # Chat with employer after a successful response.
    "chat_link": (
        'a[data-qa="vacancy-response-message"],'
        'a[data-qa="vacancy-response-message-top"],'
        'a[data-qa="vacancy-response-link-message"],'
        'a:has-text("Написать сообщение")'
    ),
    "chat_disabled": (
        'text=Работодатель не принимает сообщения,'
        'text=не принимает сообщения'
    ),
    "chat_input": (
        'textarea[data-qa="chat-send-textarea"],'
        'textarea[data-qa="message-input"],'
        'textarea[data-qa="chat-message-input"],'
        'div[data-qa="chat-input"] textarea,'
        'textarea[placeholder*="Сообщение"],'
        "textarea"
    ),
    "chat_message": '[data-qa="chat-message"]',
    # New chatik chat (jobs.tut.by / rabota.by 2026).
    "chatik_activator": (
        '[data-qa="chatikActivator-button"],'
        '[data-qa="chatik-activator-navi-item"]'
    ),
    "chatik_iframe": (
        'iframe[src*="chatik"],'
        'iframe[data-qa="chatik-integration-iframe"],'
        '.chatik-integration-iframe'
    ),
    "chatik_new_tab": '[data-qa="chatik-open-in-new-tab-button"]',
    "chatik_conversation": '[data-qa*="chatik-conversation"], [data-qa*="chatik-chat-"], [data-qa*="conversations"]',
    "chat_attach_letter": (
        '[data-qa="chatik-chat-message-applicant-action-text"],'
        'text=Добавить сопроводительное'
    ),
    "chat_send_btn": (
        '[data-qa="chatik-do-send-message"],'
        'button[aria-label*="отправить сообщение"]'
    ),
    "chat_upload_file": 'input[data-qa="upload-file-input"]',
    "chat_new_message": (
        '[data-qa="chatik-chat-message"],'
        '[data-qa="chat-message"],'
        '[data-qa*="chatik-message"]'
    ),
}
