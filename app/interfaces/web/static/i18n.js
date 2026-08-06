(() => {
  // Default: navigator.language starts with "ru" → ru, else en.
  // If browser language is unavailable, product default is ru.
  const LANG_KEY = "aa-lang";
  const STRINGS = {
    ru: {
      "tagline": "hh.ru / rabota.by · LinkedIn · launch-фильтры",
      "workspace.group": "Рабочее окружение",
      "workspace.hh": "rabota.by / hh",
      "workspace.linkedin": "LinkedIn",
      "linkedin.login": "Войти в аккаунт",
      "linkedin.network": "Расширить сеть",
      "linkedin.network.busy": "Расширяем сеть…",
      "linkedin.vacancies": "Собрать вакансии",
      "linkedin.vacancies.busy": "Собираем вакансии…",
      "linkedin.criteria": "Критерии",
      "linkedin.criteria.aria": "Задать критерии LinkedIn",
      "linkedin.tab.network": "Контакты",
      "linkedin.tab.vacancies": "Вакансии",
      "linkedin.risk": "LinkedIn: только браузерная автоматизация. Агрессивные лимиты могут привести к ограничениям аккаунта.",
      "linkedin.stats.contacts": "Контакты",
      "linkedin.stats.connected": "Connect",
      "linkedin.stats.pending": "Pending",
      "linkedin.stats.vacancies": "Вакансии LI",
      "linkedin.contacts.title": "Контакты LinkedIn",
      "linkedin.vacancies.title": "Вакансии LinkedIn",
      "linkedin.modal.title": "Критерии LinkedIn",
      "linkedin.modal.desc": "JSON → config/linkedin.launch.json",
      "th.status": "Статус",
      "th.query": "Запрос",
      "th.loc": "Локация",
      "report.schedule.hint": "Расписание PDF: след. {when} · последний {last}",
      "report.schedule.off": "Расписание PDF выключено (REPORT_SCHEDULE_ENABLED)",
      "parse.schedule.hint": "Парсинг по расписанию: {times} ({tz}) · след. {when} · последний {last}",
      "parse.schedule.off": "Расписание парсинга выключено (PARSE_SCHEDULE_ENABLED)",
      "theme.group": "Тема оформления",
      "theme.system": "Как в системе",
      "theme.system.aria": "Системная",
      "theme.light": "Светлая",
      "theme.light.aria": "Тема: светлая",
      "theme.dark": "Тёмная",
      "theme.dark.aria": "Тема: тёмная",
      "lang.group": "Язык интерфейса",
      "lang.switch": "Переключить язык",
      "lang.ru.aria": "Русский",
      "lang.en.aria": "English",
      "profile.label": "Профиль",
      "profile.select": "Профиль",
      "profile.placeholder": "новый профиль",
      "profile.add": "Добавить",
      "profile.add.aria": "Добавить профиль",
      "profile.rename": "Переименовать",
      "profile.rename.prompt": "Новое имя профиля:",
      "profile.delete": "Удалить",
      "profile.delete.confirm": "Удалить профиль «{name}»? Вакансии, отклики, журнал и сессии будут стёрты.",
      "launch.label": "Параметры запуска (строгий формат → config/launch.json)",
      "launch.aria": "Параметры запуска",
      "launch.summary.label": "Критерии запуска",
      "launch.criteria": "Критерии",
      "launch.criteria.edit": "Задать критерии",
      "launch.criteria.aria": "Задать критерии запуска",
      "launch.modal.title": "Критерии запуска",
      "launch.close": "Закрыть",
      "launch.meta.empty": "Нет launch.json — откройте «Критерии»",
      "launch.meta.placeholder": "site / city / salary / level / queries…",
      "launch.validate": "Проверить",
      "launch.save": "Сохранить",
      "launch.ok": "OK — формат и локация валидны",
      "launch.err.validate": "ошибка валидации",
      "launch.err.save": "не сохранено",
      "launch.saved": "Сохранено → {path}",
      "login.connect": "Войти в аккаунт",
      "remote.open": "Открыть браузер",
      "remote.show": "Показать браузер",
      "session.save": "Сохранить сессию входа",
      "session.save.title": "Сохранить cookies после ручного входа",
      "session.save.hint": "После входа нажмите «Сохранить сессию входа».",
      "session.invalid": "Сессия недействительна или истекла — войдите снова и сохраните сессию.",
      "session.missing": "Нет сохранённой сессии — войдите и сохраните вход.",
      "session.save.reminder": "Вошли? Сохраните сессию входа.",
      "empty.yet": "Пока пусто",
      "search": "Искать вакансии",
      "search.busy": "Идёт поиск",
      "apply": "Откликнуться на вакансии",
      "apply.busy": "Идёт отклик",
      "stop": "Остановить",
      "close": "Закрыть",
      "return": "Вернуться",
      "status.ready": "Готово к работе",
      "remote.hint": "Браузер на сервере: screencast. Войдите на rabota.by в окне ниже.",
      "remote.title": "Браузер",
      "remote.close": "Закрыть",
      "remote.fullscreen": "На весь экран",
      "remote.fullscreen_exit": "Вернуться",
      "remote.connecting": "Подключение…",
      "remote.waiting_frames": "Ожидание кадров…",
      "remote.closed": "закрыто",
      "remote.ws_error": "Ошибка WebSocket",
      "remote.conn_closed": "Соединение закрыто",
      "remote.help": "Тап/клик = фокус. Ввод идёт на серверный Chromium.",
      "stats.queued": "В очереди",
      "stats.applied": "Отклики",
      "stats.session": "Сессия",
      "stats.session_ok": "ok",
      "stats.session_no": "нет",
      "queue.title": "Вакансии",
      "th.cat": "Кат.",
      "th.score": "Score",
      "th.title": "Вакансия",
      "th.filter": "Фильтр",
      "th.apply": "Отклик",
      "log.title": "Журнал",
      "log.expand": "Развернуть на весь экран",
      "log.collapse": "Свернуть",
      "explain.title": "Почему такой score",
      "explain.close": "Закрыть",
      "explain.pos": "Плюсы",
      "explain.neg": "Минусы",
      "explain.loading": "Считаем веса…",
      "vac.explain": "Пояснить",
      "status.idle": "ожидание",
      "status.searching": "поиск",
      "status.applying": "отклик",
      "status.waiting": "ожидание",
      "status.waiting_user": "ждёт вас",
      "status.logging_in": "логин",
      "status.error": "ошибка",
      "status.done": "готово",
      "status.busy": "занято",
      "status.linkedin_network": "сеть",
      "status.linkedin_vacancies": "вакансии LI",
      "alert.last": "Последний алерт ({event}): {message}",
      "report.label": "Отчёт",
      "report.kind": "Тип отчёта",
      "report.kind.hh": "rabota / hh",
      "report.kind.linkedin": "LinkedIn",
      "report.kind.work": "Работа",
      "report.kind.queue": "Очередь",
      "report.kind.launch": "Launch",
      "report.download": "Скачать отчёт",
      "report.download.aria": "Скачать PDF-отчёт",
    },
    en: {
      "tagline": "hh.ru / rabota.by · LinkedIn · launch filters",
      "workspace.group": "Work environment",
      "workspace.hh": "rabota.by / hh",
      "workspace.linkedin": "LinkedIn",
      "linkedin.login": "Sign in to account",
      "linkedin.network": "Grow network",
      "linkedin.network.busy": "Growing network…",
      "linkedin.vacancies": "Collect jobs",
      "linkedin.vacancies.busy": "Collecting jobs…",
      "linkedin.criteria": "Criteria",
      "linkedin.criteria.aria": "Edit LinkedIn criteria",
      "linkedin.tab.network": "Contacts",
      "linkedin.tab.vacancies": "Jobs",
      "linkedin.risk": "LinkedIn: browser automation only. Aggressive limits may trigger account restrictions.",
      "linkedin.stats.contacts": "Contacts",
      "linkedin.stats.connected": "Connect",
      "linkedin.stats.pending": "Pending",
      "linkedin.stats.vacancies": "LI jobs",
      "linkedin.contacts.title": "LinkedIn contacts",
      "linkedin.vacancies.title": "LinkedIn jobs",
      "linkedin.modal.title": "LinkedIn criteria",
      "linkedin.modal.desc": "JSON → config/linkedin.launch.json",
      "th.status": "Status",
      "th.query": "Query",
      "th.loc": "Location",
      "report.schedule.hint": "PDF schedule: next {when} · last {last}",
      "report.schedule.off": "PDF schedule off (REPORT_SCHEDULE_ENABLED)",
      "parse.schedule.hint": "Parse schedule: {times} ({tz}) · next {when} · last {last}",
      "parse.schedule.off": "Parse schedule off (PARSE_SCHEDULE_ENABLED)",
      "theme.group": "Color theme",
      "theme.system": "System",
      "theme.system.aria": "Match device",
      "theme.light": "Light",
      "theme.light.aria": "Theme: light",
      "theme.dark": "Dark",
      "theme.dark.aria": "Theme: dark",
      "lang.group": "Interface language",
      "lang.switch": "Switch language",
      "lang.ru.aria": "Russian",
      "lang.en.aria": "English",
      "profile.label": "Profile",
      "profile.select": "Profile",
      "profile.placeholder": "new profile",
      "profile.add": "Add",
      "profile.add.aria": "Add profile",
      "profile.rename": "Rename",
      "profile.rename.prompt": "New profile name:",
      "profile.delete": "Delete",
      "profile.delete.confirm": "Delete profile “{name}”? Vacancies, applications, logs and sessions will be wiped.",
      "launch.label": "Launch parameters (strict format → config/launch.json)",
      "launch.aria": "Launch profile",
      "launch.summary.label": "Launch criteria",
      "launch.criteria": "Criteria",
      "launch.criteria.edit": "Edit criteria",
      "launch.criteria.aria": "Edit launch criteria",
      "launch.modal.title": "Launch criteria",
      "launch.close": "Close",
      "launch.meta.empty": "No launch.json — open Criteria",
      "launch.meta.placeholder": "site / city / salary / level / queries…",
      "launch.validate": "Validate",
      "launch.save": "Save",
      "launch.ok": "OK — format and location are valid",
      "launch.err.validate": "validation error",
      "launch.err.save": "not saved",
      "launch.saved": "Saved → {path}",
      "login.connect": "Sign in to account",
      "remote.open": "Open browser",
      "remote.show": "Show browser",
      "session.save": "Save sign-in session",
      "session.save.title": "Persist cookies after manual sign-in",
      "session.save.hint": "After sign-in, press “Save sign-in session”.",
      "session.invalid": "Session expired or invalid — sign in again and save the session.",
      "session.missing": "No saved session — sign in and save it.",
      "session.save.reminder": "Signed in? Save the sign-in session.",
      "empty.yet": "Nothing yet",
      "search": "Search vacancies",
      "search.busy": "Searching…",
      "apply": "Apply to vacancies",
      "apply.busy": "Applying…",
      "stop": "Stop",
      "close": "Close",
      "return": "Return",
      "status.ready": "Ready",
      "remote.hint": "Server browser screencast. Sign in to rabota.by in the window below.",
      "remote.title": "Browser",
      "remote.close": "Close",
      "remote.fullscreen": "Fullscreen",
      "remote.fullscreen_exit": "Return",
      "remote.connecting": "Connecting…",
      "remote.waiting_frames": "Waiting for frames…",
      "remote.closed": "closed",
      "remote.ws_error": "WebSocket error",
      "remote.conn_closed": "Connection closed",
      "remote.help": "Tap/click to focus. Input goes to the server Chromium.",
      "stats.queued": "Queued",
      "stats.applied": "Applied",
      "stats.session": "Session",
      "stats.session_ok": "ok",
      "stats.session_no": "no",
      "queue.title": "Vacancies",
      "th.cat": "Cat",
      "th.score": "Score",
      "th.title": "Title",
      "th.filter": "Filter",
      "th.apply": "Apply",
      "log.title": "Journal",
      "explain.title": "Why this score",
      "explain.close": "Close",
      "explain.pos": "Pros",
      "explain.neg": "Cons",
      "explain.loading": "Scoring…",
      "vac.explain": "Explain",
      "status.idle": "idle",
      "status.searching": "searching",
      "status.applying": "applying",
      "status.waiting": "waiting",
      "status.waiting_user": "waiting for you",
      "status.logging_in": "logging in",
      "status.error": "error",
      "status.done": "done",
      "status.busy": "busy",
      "status.linkedin_network": "network",
      "status.linkedin_vacancies": "LI jobs",
      "alert.last": "Last alert ({event}): {message}",
      "report.label": "Report",
      "report.kind": "Report type",
      "report.kind.hh": "rabota / hh",
      "report.kind.linkedin": "LinkedIn",
      "report.kind.work": "Work done",
      "report.kind.queue": "Queue",
      "report.kind.launch": "Launch",
      "report.download": "Download report",
      "report.download.aria": "Download PDF report",
    },
  };

  let current = "ru";

  function detectLang() {
    try {
      const saved = localStorage.getItem(LANG_KEY);
      if (saved === "ru" || saved === "en") return saved;
    } catch (_) {}
    try {
      const nav = (navigator.language || navigator.userLanguage || "").toLowerCase();
      if (nav) return nav.startsWith("ru") ? "ru" : "en";
    } catch (_) {}
    return "ru";
  }

  function t(key, vars) {
    const table = STRINGS[current] || STRINGS.ru;
    let s = table[key] ?? STRINGS.en[key] ?? key;
    if (vars) {
      Object.keys(vars).forEach((k) => {
        s = s.replaceAll(`{${k}}`, String(vars[k]));
      });
    }
    return s;
  }

  function applyI18n(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      const val = t(key);
      const attrs = (el.getAttribute("data-i18n-attr") || "")
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean);
      attrs.forEach((a) => el.setAttribute(a, val));
      const isField =
        el instanceof HTMLInputElement ||
        el instanceof HTMLTextAreaElement ||
        el instanceof HTMLSelectElement;
      if (isField) return;
      if (attrs.length && el.children.length && el.getAttribute("data-i18n-text") !== "1") {
        return;
      }
      el.textContent = val;
    });
  }

  function syncLangSwitch() {
    document.querySelectorAll("[data-lang-set]").forEach((btn) => {
      const on = btn.getAttribute("data-lang-set") === current;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    const sw = document.getElementById("langSwitch");
    if (sw) {
      sw.dataset.lang = current;
    }
  }

  function setLang(lang) {
    current = lang === "en" ? "en" : "ru";
    try {
      localStorage.setItem(LANG_KEY, current);
    } catch (_) {}
    document.documentElement.setAttribute("lang", current);
    applyI18n(document);
    syncLangSwitch();
    window.dispatchEvent(new CustomEvent("aa:lang", { detail: { lang: current } }));
  }

  function getLang() {
    return current;
  }

  function initLang() {
    document.querySelectorAll("[data-lang-set]").forEach((btn) => {
      btn.addEventListener("click", () => {
        setLang(btn.getAttribute("data-lang-set"));
      });
    });
    setLang(detectLang());
  }

  window.AA_I18N = { LANG_KEY, t, getLang, setLang, applyI18n, initLang, detectLang };
})();
