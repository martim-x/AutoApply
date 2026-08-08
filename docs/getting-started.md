# Запуск и назначение auto-apply-app

Кратко: **на что рассчитан** продукт и **как поднять** его локально / в Docker.

Подробнее по UI → [user-guide.md](./user-guide.md).  
Приоритеты из Legend → [priorities.md](./priorities.md).  
Архитектура → [architecture.md](./architecture.md).  
Docker / Railway → [docker-railway.md](./docker-railway.md).  
LinkedIn workspace → [linkedin.md](./linkedin.md).

---

## На что рассчитан запуск

auto-apply-app — **личный робот откликов** для кандидата Middle+ Python (профиль из Obsidian `07 Legend`):

| Цель | Как закрывается |
|------|-----------------|
| Искать вакансии на **rabota.by** / **hh.ru** | Playwright + сохранённая браузерная сессия (без OAuth API) |
| LinkedIn networking + сбор ссылок на вакансии | Отдельный workspace в UI (тоже browser-only) |
| Ежедневный PDF-отчёт | In-process scheduler (`REPORT_SCHEDULE_*`) → `data/reports/` |
| Парсинг вакансий 2×/день | In-process scheduler (`PARSE_SCHEDULE_*`, 12:00 + 00:00) |
| Не тратить время на мусор | Жёсткие фильтры + весовой граф → HIGH / MEDIUM / LOW |
| Откликаться в порядке приоритета | Очередь HIGH → MEDIUM → LOW + универсальное письмо |
| Работать локально и на headless-хосте | Видимый Chromium **или** remote screencast в UI |

### Для кого

- Один пользователь / несколько **профилей** (разные `storage_state`)
- Ручной логин один раз → дальше cookies на диске
- Не корпоративный ATS и не публичный SaaS multi-tenant

### На что **не** рассчитан

- Автологин по паролю / обход 2FA и captcha
- Официальный HH OAuth API (у BY был `geo_forbidden` — сознательно ушли в браузер)
- Массовый спам без лимитов (есть rate limits час/сутки)
- «Умный» подбор работодателя: модель — **правила + веса**, не LLM

### Типичный сценарий дня

1. Поднять сервер → открыть UI  
2. Задать / проверить **launch-профиль** (сайт, город, вилка, queries)  
3. Login → сессия  
4. Search → очередь с score  
5. Apply (или `dry_run: true` для прогона без отправки)  
6. Смотреть журнал + Explain у спорных вакансий  

---

## Требования

- macOS / Linux (Windows — на свой страх, Playwright ок)
- Python **3.11–3.14**
- [Poetry](https://python-poetry.org/) 2.x
- Chromium для Playwright

---

## Быстрый старт (Poetry)

Из корня репозитория:

```bash
poetry install

# если Cursor выставил sandbox-путь браузеров — сбросьте
unset PLAYWRIGHT_BROWSERS_PATH
poetry run playwright install chromium

cp -n .env.example .env
# при первом запуске можно оставить .env как есть

poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
# или: poetry run autoapply
```

Откройте: **http://127.0.0.1:8080**

Тесты:

```bash
poetry run pytest -q
```

### Если Playwright пишет «Executable doesn't exist»

```bash
unset PLAYWRIGHT_BROWSERS_PATH
poetry run playwright install chromium
```

В коде есть fallback на системный Chrome (`channel="chrome"`), но штатный путь — установленный Chromium Playwright.

---

## Launch-профиль — главный «на что ищем»

Файл `config/launch.json` (в `.gitignore`) или блок **«Параметры запуска»** в UI.  
Пример: `config/launch.example.json`.

```text
site: rabota.by
country: Беларусь
city: Минск
strict: true
queries: python-разработчик, python-developer
remote_or_hybrid: true
skip_gov: true
python_keywords: true
apply_limit: 30
dry_run: false
salary_min_usd: 2200
salary_max_usd: 2800
salary_strict: false
level: middle+
```

| Поле | Смысл |
|------|--------|
| `site` | `rabota.by` или `hh.ru` (страна должна совпасть) |
| `country` / `city` | строго из `config/areas.json` → HH `area=` |
| `strict` | `true` — SERP по городу + резать другой город; `false` — **вся страна** (`area` = `country_area_id`, для Беларуси `16`) |
| `queries` | поисковые строки SERP |
| `remote_or_hybrid` | обязательный remote/hybrid |
| `skip_gov` | резать `*.gov.*` и gov-маркеры |
| `python_keywords` | нужен python/разработчик-сигнал |
| `apply_limit` | сколько подходящих держать в очереди за прогон |
| `dry_run` | не жать «Откликнуться», только пройти сценарий |
| `salary_*` | вилка Legend $2200–2800; `salary_strict` — жёсткий отсев ниже |
| `level` | целевой уровень для сигналов scoring |

Пока нет `launch.json`, подхватывается example (или defaults из `.env`).

После правок в UI: **Проверить** → **Сохранить фильтры**.

### Поиск по всей стране

Один launch уже может покрыть всю Беларусь (или всю Россию на hh.ru):

```text
site: rabota.by
country: Беларусь
city: Минск
strict: false
```

- `strict: false` → в SERP уходит `area=16` (страна), а не area города.
- `city` всё ещё нужен для резолва каталога и мягкого scoring по городу.
- Несколько городов / несколько `area=` в одном URL — **пока нет** (будущее: список cities/areas).

---

## Режимы логина

### A) Локальный видимый браузер (по умолчанию)

```env
HEADLESS=false
ENABLE_REMOTE_BROWSER=false
```

**Login / Connect** → окно Chromium → войти руками → **Сессия сохранена**.

### B) Remote browser в вкладке UI (Railway / Docker / без дисплея)

```env
HEADLESS=true
ENABLE_REMOTE_BROWSER=true
```

**Открыть браузер / Login** → screencast → клики/клавиатура в модалке → **Сессия сохранена**.

---

## Docker и Railway

Кратко: `docker compose up --build` → http://127.0.0.1:8080; Chromium в образе.  
Полная инструкция (volumes, env, один сервис Railway) → [docker-railway.md](./docker-railway.md).

---

## Расписание PDF-отчётов

В том же процессе uvicorn (без sidecar). По умолчанию выключено (`REPORT_SCHEDULE_ENABLED=false`).

```env
REPORT_SCHEDULE_ENABLED=true
REPORT_SCHEDULE_TIMEZONE=Europe/Minsk
REPORT_SCHEDULE_HOUR=4
REPORT_SCHEDULE_MINUTE=0
# или: REPORT_SCHEDULE_CRON=0 4 * * *
REPORT_SCHEDULE_KIND=work
REPORT_SCHEDULE_PROFILE=default
```

PDF пишется в `data/reports/`, событие — в журнал; при включённом `ALERT_SMTP_*` уходит **HTML-письмо + PDF-вложение** на `ALERT_SMTP_TO` (тот же SMTP-канал, что и алерты).  
Вручную: `GET /api/reports/{kind}.pdf` или `POST /api/reports/save` (опционально `"email": true` в теле).

Timezone — IANA (`Europe/Minsk` и т.п.); час/минута считаются в этом поясе.

---

## Расписание парсинга вакансий

Отдельно от PDF (рекрутеры чаще постят утром/вечером → **12:00 и 00:00**).  
Локально по умолчанию `PARSE_SCHEDULE_ENABLED=false`. На Railway — `true` после сохранения сессий.

Времена, timezone, bitmask задач и флаг email после cron живут в `launch.json` → `schedule` (редактор в UI «Критерии»).  
Смена времён в **Criteria → Save** подхватывается процессом **без redeploy** (планировщик перечитывает `launch.json` каждые ≤30 с; после Save — сразу).  
`PARSE_SCHEDULE_ENABLED` — **kill-switch** в env: `false` глушит стрельбу даже если в профиле `enabled=true`.  
Первый перевод kill-switch `false`→`true` по-прежнему требует **рестарта** процесса (иначе цикл планировщика не стартует).  
`PARSE_SCHEDULE_TIMES` / `PARSE_SCHEDULE_TIMEZONE` — fallback, если в launch нет `schedule`.

```env
PARSE_SCHEDULE_ENABLED=true
PARSE_SCHEDULE_PROFILE=default
PARSE_EARLY_STOP_ENABLED=true
PARSE_OLD_STREAK_STOP=0
PARSE_MAX_SERP_PAGES=20
PARSE_DUP_PAGE_STOP=3
```

Bitmask `cron_job_rules` (4 символа `0`/`1`, слева направо): HH search · HH apply · LI vacancies · LI network.  
Пример `1111` = все четыре; `1010` = только search + LI vacancies.

Для smoke: в UI Criteria поставьте ближайший слот (или временно `PARSE_SCHEDULE_TIMES` как fallback) и `REPORT_SCHEDULE_HOUR/MINUTE` на 1–3 мин позже; после проверки верните `00:00,12:00` / report `04:00`.

При срабатывании (если сессии есть): волна 1 — HH search + LI vacancies; волна 2 — HH apply + LI network (по битам).  
После успешного прогона при `email_report_after_run` — HTML-письмо + PDF (тот же `ALERT_SMTP_*`).  
Дубликаты (URL / `vacancy_id`) → `filtered:duplicate`. SERP newest-first; early-stop после `PARSE_DUP_PAGE_STOP` полностью дублирующих страниц.

В UI рядом с блоком отчёта — подсказки «парсинг по расписанию» и «расписание PDF» (след. / последний запуск).

---

## Admin `/admin` (редактор `.env`)

- Включается только если заданы **оба**: `ADMIN_USER` и `ADMIN_PASSWORD`.
- Сессия — signed cookie (`ADMIN_SECRET` рекомендуется в проде).
- Форма: имя + пароль → textarea с `.env` → Сохранить.
- Пароли в репозиторий не коммитить (только пустые ключи в `.env.example`).

---

## Важные пути на диске

| Путь | Что |
|------|-----|
| `data/config/launch.json` | HH критерии + `schedule` (UI Save; на Railway volume; не коммитить) |
| `data/config/linkedin.launch.json` | LinkedIn критерии |
| `config/launch.example.json` | пример HH launch (в образе) |
| `config/weights.json` | дерево весов scoring |
| `config/areas.json` | каталог стран/городов → `area_id` |
| `data/auto_apply_app.sqlite` | очередь, логи, статусы (создаётся пустой при первом старте; legacy `rabota_apply.sqlite` переименовывается; `RESET_DB=true` — разовый сброс) |
| `data/sessions/<profile>.storage.json` | cookies Playwright |
| `letters/` | шаблоны сопроводительных (3 стиля) |
| `.env` | секреты и оверрайды (не коммитить) |

---

## Минимальный чеклист «всё ок»

1. `poetry run pytest -q` — зелёный  
2. UI открывается, тема переключается  
3. Launch **Проверить** без ошибок  
4. Login → Session = ok в статистике  
5. Search с `dry_run: true` / малым `apply_limit`  
6. Explain у вакансии показывает плюсы/минусы  
