# AutoApply

**Язык:** русский (этот файл) · [English](README.en.md)

Личный монолит для поиска вакансий и автооткликов на rabota.by, hh.ru и LinkedIn. Один процесс: Web UI, REST API, Playwright-воркер и база (SQLite по умолчанию, Postgres по желанию).

Подробные заметки по слоям и сценариям лежат в [`docs/`](docs/). Этот README собирает канон: зачем продукт, что умеет, на чём собран, какие решения зафиксированы, как поднять локально и на PaaS.

---

## 1. О проекте

AutoApply закрывает ежедневный контур кандидата Middle+ Python (профиль из Obsidian `07 Legend`): найти релевантные вакансии, отсеять мусор жёсткими фильтрами, оценить fit весовым графом, откликнуться в порядке HIGH → MEDIUM → LOW и при необходимости расширить сеть на LinkedIn.

Сессия на площадках строится через ручной логин в браузере и сохранение Playwright `storage_state` (cookies). Официальный HH OAuth для BY давал `geo_forbidden`, поэтому выбран браузерный путь. LinkedIn тоже только через автоматизацию UI.

| Вопрос | Ответ |
|--------|--------|
| Для кого | Один владелец, несколько именованных профилей (разные сессии и очереди) |
| Что делает | Поиск и отклики на rabota.by / hh.ru; networking и сбор ссылок на вакансии LinkedIn |
| Как хранит данные | SQLite в `data/` или Postgres по `DATABASE_URL`; сессии и PDF рядом в `data/` |
| Чем не является | Публичный multi-tenant SaaS, ATS компании, обход 2FA/captcha, LLM-ранжирование |

Типичный день: поднять сервис → проверить launch-критерии → Login → Search → смотреть очередь и Explain → Apply (сначала с `dry_run: true`).

---

## 2. Возможности

| Область | Что даёт продукт |
|---------|------------------|
| Launch-профиль HH | Сайт, страна, город, queries, remote/hybrid, skip gov, python-keywords, вилка USD, level, лимиты, dry_run |
| Фильтры | Бинарный pass/fail до постановки в очередь (офис-only, gov, чужой город при `strict`, salary_strict) |
| Scoring | Дерево весов `config/weights.json` → score 0-100 → HIGH / MEDIUM / LOW + Explain в UI |
| Очередь откликов | Порядок HIGH → MEDIUM → LOW; письмо из `letters/` (`LETTER_STYLE`) |
| LinkedIn workspace | Отдельная вкладка: Connect по people search, сбор vacancy links, свой `linkedin.launch.json` |
| Remote browser | CDP screencast в модалке UI (логин на Docker / Railway / Fly без GUI) |
| Профили | Несколько профилей с изолированными сессиями HH и LinkedIn |
| Расписания | PDF-отчёт и парсинг вакансий 2×/день в том же процессе uvicorn |
| Алерты | SMTP при captcha / error / parse-fail с rate-limit |
| UI | Jinja + vanilla JS/CSS; тема system / light / dark; mobile layout; панели очереди и журнала |
| Защита | Owner gate `/login` и Admin `/admin` при заданных `ADMIN_*` / `GATE_*` |
| Управление job | Start search / apply / LinkedIn actions, Stop текущего слота |

---

## 3. Технологический стек

| Слой | Выбор |
|------|--------|
| Язык | Python 3.11-3.14 (`requires-python` в `pyproject.toml`; CI на 3.12) |
| Пакетный менеджер | Poetry (`pyproject.toml` + `poetry.lock`); `requirements.txt` - экспорт для Docker |
| Web / API | FastAPI, Uvicorn, Jinja2, Starlette sessions, PyJWT |
| Браузер | Playwright Chromium (образ `mcr.microsoft.com/playwright/python`) |
| Remote UI | CDP `Page.startScreencast` → JPEG по WebSocket |
| БД | SQLite по умолчанию; Postgres через SQLAlchemy + psycopg3 |
| Отчёты | ReportLab (PDF) |
| Конфиг | pydantic-settings из `.env`; launch JSON / text DSL |
| Контейнер | Multi-stage `Dockerfile`, `docker-compose.yml` |
| PaaS | Fly.io (`fly.toml`) и Railway (Deploy from Dockerfile; отдельного `railway.toml` / Procfile в репо нет) |
| CI | GitHub Actions: ruff + mypy + pytest на push/PR в `main` (деплоя из Actions нет) |

---

## 4. Архитектура и решения

Формальных файлов ADR (`ADR-001` и т.п.) в репозитории нет. Зафиксированные решения живут в [`docs/architecture.md`](docs/architecture.md) и соседних гайдах. Ниже - сжатая карта «зачем так», чтобы можно было сразу зацепиться за смысл.

### Слои (DDD-монолит)

```
interfaces  →  application  →  domain
                  ↑
            infrastructure
```

| Слой | Ответственность | Где смотреть |
|------|-----------------|--------------|
| domain | Фильтры, scoring, launch/linkedin profile, ports | `app/domain/` |
| application | Use-cases: login, search, apply, explain, alerts, reports | `app/application/` |
| infrastructure | Settings, SQLite/Postgres UoW, Playwright, remote CDP, schedulers, SMTP | `app/infrastructure/` |
| interfaces | HTTP, WebSocket, Jinja UI, owner gate, admin | `app/interfaces/` |

### Ключевые решения

| Решение | Контекст | К чему пришли | Документ / код |
|---------|----------|---------------|----------------|
| Один процесс FastAPI | Личный инструмент, статус job в одном месте | Web + API + worker + scheduler в uvicorn | `app/main.py` |
| Browser session вместо HH OAuth | Для BY был `geo_forbidden` | Ручной логин → `storage_state` на диск | `docs/architecture.md` §2 |
| Launch.json как источник прогона | Нужен один артефакт «как ищу сегодня» | Перекрывает `.env` для site/area/queries/фильтров | `app/domain/launch_profile.py` |
| Фильтр, затем score | Офис-only и gov не должны засорять очередь как LOW | Сначала pass/fail, потом weight-graph | `filters.py`, `scoring/` |
| Remote screencast | На PaaS нет нормального GUI | CDP JPEG + ввод в модалке | `remote_session.py` |
| Два слота Chromium на профиль | HH и LinkedIn параллельно | `profile:hh` и `profile:linkedin` | `docs/linkedin.md` |
| SQLite по умолчанию | Zero-ops локально | Файл в `data/`; Postgres опционально | `docs/docker-railway.md` |
| CI без deploy | Проверки отдельно от выкладки | Actions только lint/test; deploy вручную / Fly GitHub integration / Railway | `docs/fly-io.md` |

### Карта каталогов

```
app/
  domain/           # правила и порты
  application/      # use-cases
  infrastructure/   # БД, браузер, settings, alerts, schedulers
  interfaces/       # API, Web UI, auth, admin
config/             # areas, weights, launch*.example.json
data/               # sqlite, sessions, reports (в git не коммитить секреты)
docs/               # углублённые гайды
tests/
letters/            # шаблоны сопроводительных (3 стиля)
letter_universal.txt  # legacy: один файл, если LETTER_PATH указывает на него
```

Дополнительно:

| Документ | Тема |
|----------|------|
| [docs/architecture.md](docs/architecture.md) | Полный разбор решений |
| [docs/getting-started.md](docs/getting-started.md) | Назначение и первый подъём |
| [docs/user-guide.md](docs/user-guide.md) | Пошаговый UI |
| [docs/linkedin.md](docs/linkedin.md) | LinkedIn workspace |
| [docs/docker-railway.md](docs/docker-railway.md) | Docker Compose и Railway |
| [docs/fly-io.md](docs/fly-io.md) | Fly.io и границы CI |
| [docs/alerts.md](docs/alerts.md) | SMTP и durability прогона |
| [docs/priorities.md](docs/priorities.md) | Legend → фильтры и веса |

Статусы job: `idle` → `logging_in` / `waiting_user` → `searching` → `applying` → `done` | `error`. Stop прерывает текущий слот (и remote browser при необходимости).

---

## 5. Руководство по использованию

### 5.1. Требования

| Что | Версия / заметка |
|-----|------------------|
| ОС | macOS / Linux (Windows на свой страх; Playwright поддерживается) |
| Python | 3.11-3.14 |
| Poetry | 2.x (в Docker и CI: 2.1.3) |
| Браузер | Chromium через `poetry run playwright install chromium` |

### 5.2. Локальный запуск

Контекст: вы в корне репозитория, хотите видимый Chromium для логина и UI на машине разработчика.

```bash
poetry install

# Если среда выставила sandbox-путь браузеров (Cursor и похожие) - сбросьте
unset PLAYWRIGHT_BROWSERS_PATH
poetry run playwright install chromium

cp -n .env.example .env
# При первом запуске можно оставить значения по умолчанию

poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
# или: poetry run autoapply
```

| Шаг | Деталь |
|-----|--------|
| UI | http://127.0.0.1:8080 |
| Порт | `PORT` в `.env` (по умолчанию 8080); uvicorn в команде выше тоже задаёт 8080 |
| Тесты | `poetry run pytest -q` |
| Playwright «Executable doesn't exist» | Снова `unset PLAYWRIGHT_BROWSERS_PATH` и `poetry run playwright install chromium` |

Рекомендуемые значения для локального видимого браузера:

```env
HEADLESS=false
ENABLE_REMOTE_BROWSER=false
```

Конфиги, которые стоит проверить до первого Search:

| Путь | Назначение |
|------|------------|
| `.env` | Секреты и оверрайды (из `.env.example`) |
| `config/launch.json` | Прогон HH (пример: `config/launch.example.json`; файл в `.gitignore`) |
| `config/linkedin.launch.json` | Критерии LinkedIn (пример: `linkedin.launch.example.json`) |
| `config/areas.json` | Каталог стран/городов → HH `area_id` |
| `config/weights.json` | Дерево весов scoring |
| `letters/` | Шаблоны отклика (случайный стиль на каждый apply) |
| `data/` | SQLite, `sessions/`, `reports/` (создаётся при старте) |

Пока нет `launch.json`, сервис подхватывает example или defaults из `.env`.

#### Локально через Docker Compose

```bash
cp -n .env.example .env
docker compose up --build
```

| Что | Где |
|-----|-----|
| UI | http://127.0.0.1:8080 |
| Данные | том `./data` → `/app/data` |
| Конфиг | `./config` → `/app/config` |
| Env в контейнере | `HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true` (жёстко в compose, даже если локальный `.env` говорит иначе) |
| Healthcheck | `GET /api/health` |

### 5.3. Переменные окружения

Источник правды: [`.env.example`](.env.example) и `app/infrastructure/settings.py`. Сервис **стартует без обязательных секретов**: пустой `.env` с дефолтами достаточен для локального UI и SQLite. Секреты нужны для owner gate, admin, SMTP и продакшен-кук.

Ниже «обязательно» значит «нужно осознанно задать для этого сценария». Для холодного старта локально все строки optional.

#### Приложение и пути

| Переменная | Обяз. | По умолчанию / пример | Смысл |
|------------|-------|------------------------|--------|
| `APP_NAME` | нет | `auto-apply-app` | Имя приложения (заголовок FastAPI) |
| `HOST` | нет | `0.0.0.0` | Bind-адрес |
| `PORT` | нет | `8080` | Порт (на Railway подхватывается `PORT` платформы в CMD) |
| `DEBUG` | нет | `false` | Режим отладки |
| `DATA_DIR` | нет | `./data` | Корень данных |
| `SESSIONS_DIR` | нет | `./data/sessions` | Cookies Playwright (можно не задавать) |
| `LETTER_PATH` | нет | `./letters` | Файл или каталог `*.txt` писем |
| `LETTER_STYLE` | нет | `rotate` | `rotate` / `impact` / `responsibility` / `project` |
| `LAUNCH_PATH` | нет | `./data/config/launch.json` | HH launch-профиль (на volume; Railway: `/app/data/config/launch.json`) |
| `LINKEDIN_LAUNCH_PATH` | нет | `./data/config/linkedin.launch.json` | LinkedIn launch |

#### База данных

| Переменная | Обяз. | Пример | Смысл |
|------------|-------|--------|--------|
| `DATABASE_URL` | нет* | `sqlite:///./data/auto_apply_app.sqlite` | SQLite по умолчанию. На пустом volume файл и схема создаются сами. Legacy `rabota_apply.sqlite` переименовывается при старте |
| `DATABASE_URL` (Postgres) | нет* | `postgresql://user:pass@host:5432/railway` или `postgresql+psycopg://…` | Тот же UnitOfWork; приложение нормализует `postgresql://` → `postgresql+psycopg://` |
| `DB_PASSWORD` | нет | (пусто) | Зарезервировано; обычно пароль уже в URL |
| `RESET_DB` | нет | `false` | `true` один раз → уничтожить SQLite / сбросить public schema Postgres, затем вернуть `false` |

\* Для работы нужна валидная БД. Дефолтный SQLite-путь закрывает локальный старт без правок.

#### Поиск HH (defaults; перекрываются `launch.json`)

| Переменная | Обяз. | По умолчанию | Смысл |
|------------|-------|--------------|--------|
| `BASE_URL` | нет | `https://rabota.by` | Базовый сайт |
| `SEARCH_AREA` | нет | `16` | Fallback area |
| `SEARCH_QUERIES` | нет | python-запросы через запятую | SERP queries |
| `VACANCY_LIMIT` | нет | `30` | Сколько вакансий парсить за поиск |
| `APPLY_LIMIT` | нет | `30` | Сколько queued обработать за apply |
| `DRY_RUN` | нет | `false` | Не жать реальный «Откликнуться» |
| `REQUIRE_REMOTE_OR_HYBRID` | нет | `true` | Фильтр формата |
| `SKIP_GOV` | нет | `true` | Резать gov |
| `REQUIRE_PYTHON_KEYWORDS` | нет | `true` | Нужен python/разработчик-сигнал |

#### Браузер и remote screencast

| Переменная | Обяз. | По умолчанию | Смысл |
|------------|-------|--------------|--------|
| `HEADLESS` | нет | `false` локально; в Docker/Fly образе `true` | Без GUI |
| `ENABLE_REMOTE_BROWSER` | для PaaS без дисплея: да | `false` | Встроенный screencast в UI; при `true` код форсирует headless |
| `REMOTE_BROWSER_JPEG_QUALITY` | нет | `55` | Качество JPEG кадров |
| `REMOTE_BROWSER_EVERY_NTH_FRAME` | нет | `1` | Прореживание кадров |

#### Rate limits и retry

| Переменная | Обяз. | По умолчанию | Смысл |
|------------|-------|--------------|--------|
| `MIN_ACTION_INTERVAL` | нет | `2.0` | Пауза между действиями (сек) |
| `AFTER_APPLY_DELAY` | нет | `8.0` | Пауза после отклика |
| `JITTER` | нет | `0.35` | Разброс пауз |
| `MAX_PER_HOUR` | нет | `40` | Лимит откликов в час |
| `MAX_PER_DAY` | нет | `180` | Лимит в сутки |
| `LOAD_RETRIES` | нет | `3` | Повторы загрузки |
| `LOAD_RETRY_DELAY` | нет | `2.5` | Пауза между повторами |
| `APPLY_RETRIES` | нет | `2` | Повторы отклика |
| `NAVIGATION_TIMEOUT_MS` | нет | `45000` | Таймаут навигации |
| `CONTENT_TIMEOUT_MS` | нет | `20000` | Таймаут контента |
| `SETTLE_MS` | нет | `1200` | Пауза «усадки» DOM |

#### Owner gate и Admin

| Переменная | Обяз. | Пример формы | Смысл |
|------------|-------|--------------|--------|
| `ADMIN_USER` | для gate/admin: да | ваш логин | Общая идентичность |
| `ADMIN_PASSWORD` | для gate/admin: да | сильный пароль | Общий пароль |
| `ADMIN_SECRET` | в проде: да | `openssl rand -hex 32` или `./scripts/gen_admin_secret.sh` | Подпись JWT (`nexus_token`, `refresh_token`) и admin session |
| `GATE_USER` / `GATE_PASSWORD` | нет | (пусто) | Отдельные креды только для `/login`; иначе берутся `ADMIN_*` |
| `AUTH_COOKIE_SECURE` | за HTTPS: да | `true` на Fly/Railway | Флаг Secure у auth cookies |

Поведение:

| Условие | Результат |
|---------|-----------|
| `ADMIN_USER` + `ADMIN_PASSWORD` (или `GATE_*`) заданы | Middleware закрывает `/` и `/api/*`; публичны `/login`, `/logout`, `/api/health`, `/api/auth/refresh`, `/static/*`, `/admin*` |
| Только admin-пара | Включается и gate, и `/admin` (редактор `.env`) |
| Креды пустые | Gate выключен; `/admin` отдаёт 404 |

#### Расписание PDF

| Переменная | Обяз. | По умолчанию | Смысл |
|------------|-------|--------------|--------|
| `REPORT_SCHEDULE_ENABLED` | нет | `false` | Включить in-process планировщик PDF |
| `REPORT_SCHEDULE_TIMEZONE` | нет | `Europe/Minsk` | Часовой пояс |
| `REPORT_SCHEDULE_HOUR` / `MINUTE` | нет | `4` / `0` | Время запуска |
| `REPORT_SCHEDULE_CRON` | нет | (пусто) | `minute hour * * *` перекрывает HOUR/MINUTE |
| `REPORT_SCHEDULE_KIND` | нет | `work` | Вид отчёта |
| `REPORT_SCHEDULE_PROFILE` | нет | `default` | Профиль данных |

PDF: `data/reports/`. Вручную: `GET /api/reports/{kind}.pdf`, `POST /api/reports/save`.

#### Расписание парсинга

| Переменная | Обяз. | По умолчанию | Смысл |
|------------|-------|--------------|--------|
| `PARSE_SCHEDULE_ENABLED` | нет | `false` | Парсинг по расписанию (локально лучше выключен) |
| `PARSE_SCHEDULE_TIMEZONE` | нет | `Europe/Minsk` | Часовой пояс |
| `PARSE_SCHEDULE_TIMES` | нет | `12:00,00:00` | Список `HH:MM` |
| `PARSE_SCHEDULE_PROFILE` | нет | `default` | Профиль |
| `PARSE_EARLY_STOP_ENABLED` | нет | `true` | Early-stop по подряд идущим страницам-дубликатам (HH + LinkedIn) |
| `PARSE_OLD_STREAK_STOP` | нет | `0` | Опциональный item-streak (0 = выкл.) |
| `PARSE_MAX_SERP_PAGES` | нет | `20` | Макс. страниц SERP на query |
| `PARSE_DUP_PAGE_STOP` | нет | `3` | Остановка после N полностью дублирующих страниц |

При срабатывании: HH StartSearch и LinkedIn vacancy collect (если есть соответствующие сессии), предпочтительно параллельно. Дубликаты → `filtered:duplicate`.

#### SMTP-алерты

| Переменная | Обяз. | По умолчанию | Смысл |
|------------|-------|--------------|--------|
| `ALERT_SMTP_ENABLED` | нет | `false` | Мастер-выключатель |
| `ALERT_SMTP_HOST` | если enabled: да | (пусто) | SMTP host |
| `ALERT_SMTP_PORT` | нет | `587` | 587 STARTTLS или 465 SSL |
| `ALERT_SMTP_USER` / `PASSWORD` | по требованию сервера | (пусто) | Логин SMTP |
| `ALERT_SMTP_FROM` / `TO` | если enabled: `TO` да | (пусто) | Отправитель и получатель |
| `ALERT_SMTP_TLS` | нет | `true` | STARTTLS на 587 |
| `ALERT_ON_ERROR` / `CAPTCHA` / `PARSE_FAIL` | нет | `true` | Какие события слать |
| `ALERT_RATE_LIMIT_SECONDS` | нет | `600` | Антифлуд одинаковых писем |

Пример Yandex (пароль приложения, значения подставляете сами):

```env
ALERT_SMTP_ENABLED=true
ALERT_SMTP_HOST=smtp.yandex.ru
ALERT_SMTP_PORT=465
ALERT_SMTP_USER=you@example.com
ALERT_SMTP_PASSWORD=
ALERT_SMTP_FROM=you@example.com
ALERT_SMTP_TO=you@example.com
ALERT_SMTP_TLS=true
```

#### Прочее

| Переменная | Обяз. | Смысл |
|------------|-------|--------|
| `API_KEY` | нет | Зарезервировано на будущее (в `.env.example` закомментировано) |

`.env` и персональный `launch.json` в git не коммитятся.

### 5.4. Launch-критерии HH (rabota.by / hh.ru)

Главный артефакт прогона: `config/launch.json` или модалка **Критерии** в UI (строгий text DSL `key: value`). Пример структуры JSON: `config/launch.example.json`.

Текстовый вид в UI:

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
| `site` | `rabota.by` или `hh.ru` (страна должна совпасть с каталогом) |
| `country` / `city` | Строго из `config/areas.json` → параметр `area=` |
| `strict` | `true` — город + фильтр чужого города; `false` — **вся страна** (Беларусь `area=16`) |
| `queries` | Поисковые строки SERP |
| `remote_or_hybrid` | Обязательный remote или hybrid |
| `skip_gov` | Резать gov-маркеры и `*.gov.*` |
| `python_keywords` | Нужен сигнал python / разработчик |
| `vacancy_limit` / `apply_limit` | Лимиты поиска и откликов |
| `dry_run` | Пройти сценарий без реальной отправки |
| `salary_*` | Вилка Legend $2200-2800; `salary_strict` - жёсткий отсев ниже |
| `level` | Целевой уровень для сигналов scoring |

После правок в UI: **Проверить** → **Сохранить фильтры**.

Поиск по всей стране: `strict: false` (+ `country: Беларусь` → SERP `area=16`). Несколько городов в одном launch — пока нет.

Для hh.ru:

```text
site: hh.ru
country: Россия
city: Москва
queries: python developer
…
```

Поток отбора:

```
SERP → мягкий pre-filter (gov)
     → карточка
     → evaluate_vacancy (remote, python, location, salary_strict)
     → score → HIGH|MEDIUM|LOW
     → queued | skipped
```

### 5.5. LinkedIn

Отдельная вкладка окружения в шапке: **rabota.by / hh** ↔ **LinkedIn**. Официального API нет. Риски ограничений аккаунта реальны: держите `connect_limit` и паузы консервативными. Подробности: [docs/linkedin.md](docs/linkedin.md).

| Шаг | Действие |
|-----|----------|
| 1 | Переключить workspace на LinkedIn |
| 2 | Войти → ручной логин (окно или remote) → **Сохранить сессию** |
| 3 | Файл сессии: `data/sessions/<profile>.linkedin.storage.json` (HH-сессию не затирает) |
| 4 | **Критерии** → JSON → `config/linkedin.launch.json` |
| 5 | **Расширить сеть** (лимит = `connect_limit`) |
| 6 | Вкладка **Вакансии** → **Собрать вакансии** (лимит = `vacancy_limit`) |

Ключевые поля `linkedin.launch.example.json`:

| Ключ | Default | Смысл |
|------|---------|--------|
| `locations` | Minsk, Russia, CIS | Приоритет локаций |
| `people_queries` | HR, backend developer, … | Роли для networking |
| `vacancy_queries` | Python backend, … | Запросы вакансий |
| `connect_limit` | 15 | Максимум Connect за прогон |
| `vacancy_limit` | 40 | Максимум ссылок вакансий |
| `max_profiles_per_query` | 10 | Профилей с SERP на пару query×location |
| `min_action_interval` / `after_connect_delay` / `jitter` | 8 / 14 / 0.4 | Паузы |
| `dry_run` | false | Не жать Connect, только лог |

Отдельного `CONNECT_LIMIT` в `.env` для LinkedIn нет: правьте файл или UI **Критерии**.

### 5.6. Режимы логина и remote browser

| Режим | Env | Как пользоваться |
|-------|-----|------------------|
| Локальный видимый Chromium | `HEADLESS=false`, `ENABLE_REMOTE_BROWSER=false` | **Login / Connect** → окно браузера → войти руками → **Сессия сохранена** |
| Remote в UI | `HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true` | **Открыть браузер / Login** → модалка screencast → клики и клавиатура → **Сессия сохранена** |

Сессии:

| Workspace | Файл |
|-----------|------|
| HH / rabota | `data/sessions/<profile>.storage.json` |
| LinkedIn | `data/sessions/<profile>.linkedin.storage.json` |

На один профиль допускаются два независимых Chromium (`hh` и `linkedin`). Search/apply и LinkedIn grow/collect могут идти параллельно, если слоты свободны. WebSocket: `/api/remote-browser/ws?profile=&workspace=hh|linkedin`.

### 5.7. Панели UI и рабочие сценарии

Схема интерфейса:

```
┌─ шапка: бренд · workspace · тема · статус ─────────┐
│  профиль · действия · Критерии · отчёт / парсинг   │
│  статистика                                         │
│  ┌ очередь / контакты ┐  ┌ журнал ────────────┐   │
│  │ (+ Explain для HH)  │  │ события            │   │
│  └─────────────────────┘  └────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

| Элемент | Назначение |
|---------|------------|
| Workspace switch | HH ↔ LinkedIn |
| Профиль | Селект + создание; `●` если сессия есть |
| Критерии | Модалка launch (HH text DSL или LinkedIn JSON) |
| Тема | system / light / dark (`localStorage` ключ `aa-theme`) |
| Статистика HH | HIGH/MEDIUM/LOW, queued, applied, session |
| Статистика LinkedIn | Контакты / вакансии |
| Очередь HH | Таблица (десктоп) или карточки (&lt;860px); кнопка Explain |
| Журнал | События поиска/apply/linkedin, обновление вместе со статусом |
| Отчёт | Подсказка расписания PDF; меню сохранения/скачивания |
| Remote-панель | Статус screencast, сохранить/стоп |

Рекомендуемый безопасный прогон HH:

1. В критериях `dry_run: true`, небольшой `apply_limit` (например 5).
2. Login → Session = ok.
3. Start search → очередь + пара Explain.
4. При необходимости поправить launch / `weights.json`.
5. `dry_run: false` → Start apply.

Порядок apply: только среди `queued`, HIGH → MEDIUM → LOW. Captcha / login wall → статус `waiting_user`, прогон останавливается; при включённом SMTP уходит алерт.

### 5.8. Owner gate и Admin

| Компонент | URL | Когда доступен |
|-----------|-----|----------------|
| Owner gate | `/login` | Заданы user+password (`GATE_*` или `ADMIN_*`) |
| Logout | `/logout` | После входа |
| Admin env editor | `/admin` → `/admin/env` | Заданы `ADMIN_USER` и `ADMIN_PASSWORD` |
| Health (без auth) | `GET /api/health` | Всегда публичный для healthcheck |

Куки gate: короткий access JWT `nexus_token` (15 мин) и refresh `refresh_token` (14 дней). Admin session: signed cookie `aa_admin_session`. На HTTPS выставьте `AUTH_COOKIE_SECURE=true`. Секрет: `ADMIN_SECRET` (см. `./scripts/gen_admin_secret.sh`).

После сохранения `.env` в `/admin` нужен **Restart** процесса, чтобы новые переменные подхватились.

### 5.9. Удалённый деплой

В репозитории есть реальные пути выкладки: **Dockerfile** + **docker-compose** (локально), **Railway** (Deploy from Dockerfile, описан в docs), **Fly.io** (`fly.toml`). Файлов `railway.toml` и `Procfile` нет. GitHub Actions деплой не делает: только CI.

Общий принцип: один контейнер = Web UI + Playwright jobs + планировщики в одном uvicorn. Не поднимайте несколько реплик на один SQLite-файл.

#### Railway

Опирается на [docs/docker-railway.md](docs/docker-railway.md).

1. New Project → Deploy from GitHub (или Docker), root = корень репо, билдер берёт `Dockerfile` (Playwright base + Chromium).
2. Variables (минимум для защищённого headless-хоста):

```env
HEADLESS=true
ENABLE_REMOTE_BROWSER=true
ADMIN_USER=your_admin
ADMIN_PASSWORD=strong_password
ADMIN_SECRET=   # вывод ./scripts/gen_admin_secret.sh
AUTH_COOKIE_SECURE=true
```

3. Полезные переменные расписаний (после сохранения сессий).  
   PDF-отчёт по слоту уходит на почту через **тот же** `ALERT_SMTP_*` (HTML + PDF).  
   Для smoke можно временно поставить один `HH:MM` ≈ now+5 в `PARSE_SCHEDULE_TIMES` и соседние `REPORT_SCHEDULE_HOUR/MINUTE` — см. [docs/getting-started.md](docs/getting-started.md).

```env
DATA_DIR=/app/data
DATABASE_URL=sqlite:////app/data/auto_apply_app.sqlite
REPORT_SCHEDULE_ENABLED=true
REPORT_SCHEDULE_TIMEZONE=Europe/Minsk
REPORT_SCHEDULE_HOUR=4
REPORT_SCHEDULE_MINUTE=0
PARSE_SCHEDULE_ENABLED=true
PARSE_SCHEDULE_TIMEZONE=Europe/Minsk
PARSE_SCHEDULE_TIMES=12:00,00:00
ALERT_SMTP_ENABLED=true
# … ALERT_SMTP_HOST / TO / USER / PASSWORD …
```

4. Volume на `/app/data` (SQLite, sessions, reports). Без volume данные пропадут после редеплоя.
5. Опционально Postgres plugin: в Variables сервиса привяжите `DATABASE_URL` из Postgres (`${{Postgres.DATABASE_URL}}` или скопированный URL). Volume для сессий/PDF всё равно нужен.
6. Healthcheck: `GET /api/health`.
7. Deploy → публичный URL → Login через remote screencast → **Сохранить сессию**.
8. `/admin` для правки `.env` (нужны `ADMIN_*`) → Restart.

Railway подставляет `PORT`; CMD образа: `uvicorn … --port ${PORT:-8080}`.

Память: два Chromium на профиль примерно удваивают потребление; на платформе держите запас (часто 1-2 GB+), особенно с открытым screencast.

#### Fly.io

Опирается на [docs/fly-io.md](docs/fly-io.md) и [`fly.toml`](fly.toml).

```bash
# CLI: https://fly.io/docs/hands-on/install-flyctl/
fly auth login
fly apps create auto-apply-app
fly volumes create auto_apply_app_data --region ams --size 3 --app auto-apply-app
fly secrets set ADMIN_USER='…' ADMIN_PASSWORD='…' ADMIN_SECRET="$(openssl rand -hex 32)" --app auto-apply-app
fly deploy --app auto-apply-app
```

| Факт из `fly.toml` | Значение |
|--------------------|----------|
| App name | `auto-apply-app` (если уже есть другое имя - деплойте в существующее) |
| Region | `ams` |
| Internal port | 8080 |
| Volume | `auto_apply_app_data` → `/app/data` |
| VM | 2 GB RAM, 2 shared CPUs |
| Env в toml | `HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true`, SQLite URL |
| Machines | `min_machines_running = 1`, `auto_stop_machines = off` (чтобы жили schedules) |
| Health | `GET /api/health` |

Альтернатива ручному `fly deploy`: [Fly.io GitHub integration](https://fly.io/docs/launch/continuous-deployment-with-github/). Секрет `FLY_API_TOKEN` в GitHub Actions для этого репо не используется.

В образе есть `launch.example.json`; ваш `config/launch.json` положите через volume/SSH или свой слой сборки.

### 5.10. API (кратко)

Тело POST обычно: `{"profile":"default"}`. Для remote/login confirm добавляйте `"workspace": "hh"` или `"linkedin"`.

| Method | Path | Действие |
|--------|------|----------|
| GET | `/api/health` | Liveness (публичный) |
| GET | `/api/config` | Публичный срез настроек |
| GET/POST | `/api/launch*` | Читать / валидировать / сохранить HH launch |
| GET/POST | `/api/profiles*` | Список, создание, rename, delete |
| POST | `/api/login`, `/api/login/confirm` | Логин HH и сохранение сессии |
| POST | `/api/search`, `/api/apply`, `/api/stop` | Поиск, отклики, стоп |
| GET | `/api/status`, `/api/stats` | Статус job и статистика |
| GET | `/api/vacancies`, `/api/vacancies/explain` | Очередь и Explain |
| GET | `/api/logs` | Журнал (`service=hh\|linkedin`) |
| GET/POST | `/api/remote-browser/*` | Статус / start / save / stop |
| WS | `/api/remote-browser/ws` | Кадры + ввод |
| GET/POST | `/api/linkedin/*` | Launch, login, network, vacancies |
| GET/POST | `/api/reports*` | Список, save, PDF, generate |
| POST | `/api/auth/refresh` | Обновить access cookie |

### 5.11. Минимальный чеклист

| # | Проверка |
|---|----------|
| 1 | `poetry run pytest -q` зелёный |
| 2 | UI открывается, тема переключается |
| 3 | Launch **Проверить** без ошибок |
| 4 | Login → Session = ok |
| 5 | Search с `dry_run: true` и малым лимитом |
| 6 | Explain показывает плюсы/минусы |
| 7 | На PaaS: volume на `/app/data`, remote login, `/api/health` ок |

---

## Poetry и зависимости

Версия пакета и скрипт CLI: `pyproject.toml` (`poetry run autoapply` → `app.main:run`).  
`requirements.txt` - экспорт для окружений без Poetry; источник правды для версий - `poetry.lock`.
