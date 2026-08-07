# LinkedIn workspace (MVP)

Отдельное окружение в UI (вкладки сверху: **rabota.by / hh** ↔ **LinkedIn**).  
Официального LinkedIn API **нет** — только Playwright + ручной логин + `storage_state`.

---

## Риски

LinkedIn агрессивно ограничивает автоматизацию. Держите лимиты консервативными (`connect_limit`, длинные паузы).  
Селекторы хрупкие — централизованы в `app/infrastructure/browser/linkedin_selectors.py`; сбои пишутся в журнал (`linkedin_selector_error`).

---

## Как пользоваться

1. Переключите вкладку **LinkedIn**.
2. **Войти в LinkedIn** → войдите руками (remote screencast или локальное окно) → **Сохранить сессию**.  
   Файл: `data/sessions/<profile>.linkedin.storage.json` (не затирает HH-сессию).
3. **Критерии LI** — JSON (`config/linkedin.launch.json`).
4. **Расширить сеть** — people search по локациям/ролям → открытие профилей → Connect (skip Pending).
5. Вкладка **Вакансии** → **Собрать вакансии** — ссылки/заголовки в таблицу `linkedin_vacancies`.

---

## Конфиг `config/linkedin.launch.json`

Пример: `config/linkedin.launch.example.json`.

| Ключ | Default | Смысл |
|------|---------|--------|
| `locations` | `Minsk`, `Russia`, `CIS` | приоритет локаций в поиске |
| `people_queries` | `HR`, `backend developer`, … | роли для networking |
| `vacancy_queries` | `Python backend`, … | запросы вакансий |
| `connect_limit` | `15` | максимум Connect за прогон |
| `vacancy_limit` | `40` | максимум ссылок вакансий |
| `max_profiles_per_query` | `10` | профилей с SERP на пару query×location |
| `min_action_interval` | `8.0` | пауза между действиями (сек) |
| `after_connect_delay` | `14.0` | пауза после Connect |
| `jitter` | `0.4` | разброс пауз |
| `dry_run` | `false` | не жать Connect, только лог |

Если файла нет или ключ отсутствует — подставляются defaults + **уведомление в UI** и запись в журнал (`config_default`).

Путь можно переопределить: `LINKEDIN_LAUNCH_PATH`.

---

## Архитектура

| Слой | Файлы |
|------|--------|
| Domain | `app/domain/linkedin_profile.py`, entities `LinkedInContact` / `LinkedInVacancyLink` |
| Browser | `linkedin_gateway.py`, `linkedin_selectors.py` (отдельно от HH `gateway.py`); remote/job слот `profile:linkedin` |
| Storage | `data/sessions/<profile>.linkedin.storage.json` (не затирает HH) |
| DB | `linkedin_contacts`, `linkedin_vacancies` |
| API | `/api/linkedin/*`; remote WS с `workspace=linkedin` |
| UI | workspace switcher + вкладки Контакты / Вакансии; отдельная кнопка «Открыть браузер» |

Приоритет поиска контактов по умолчанию: **Minsk → Russia → CIS**, роли **HR** и **backend**.
