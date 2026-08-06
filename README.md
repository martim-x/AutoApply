# AutoApply (RABOTA_APPLY)

Монолит для поиска вакансий и автоматических откликов на [rabota.by](https://rabota.by): Web UI, REST API, Playwright-воркер и локальная SQLite.  
Один профиль, ручной логин в браузере, дальше — поиск и отклики роботом. Сессия хранится как cookies / `storage_state` (без OAuth `client_id`).

## Возможности

- Web UI и API в одном процессе FastAPI
- Ручной вход → сохранение Playwright-сессии → поиск → очередь → отклики
- Категории fit: **HIGH / MEDIUM / LOW** и приоритетная очередь
- Фильтры: remote или hybrid, пропуск `*.gov.*`, ключевые слова python/разработчик
- Human-like rate limits (паузы, jitter, лимиты час/сутки) и retry с backoff
- Stop текущего job в любой момент
- Локальная SQLite; порты БД готовы к внешней БД позже
- Docker / docker-compose для headless-запуска

## Требования

- Python 3.11–3.14
- [Poetry](https://python-poetry.org/) 2.x
- Chromium для Playwright (ставится командой ниже)

## Установка и запуск (Poetry)

```bash
# 1) Зависимости (создаст .venv в проекте)
poetry install

# 2) Браузер Playwright
poetry run playwright install chromium

# 3) Конфиг
cp -n .env.example .env
# отредактируйте .env при необходимости

# 4) Приложение
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
# или: poetry run autoapply
```

Откройте http://127.0.0.1:8080

Тесты:

```bash
poetry run pytest -q
```

> Источник правды по зависимостям — `pyproject.toml` + `poetry.lock`.  
> Файл `requirements.txt` оставлен как экспорт для Docker/простого pip; обновлять его:  
> `poetry export -f requirements.txt --output requirements.txt --without-hashes`  
> (нужен плагин `poetry-plugin-export`, либо скопируйте версии из `poetry show`).

## Как пользоваться (UI)

Один профиль (по умолчанию `default`):

1. **Login / Connect** — откроется браузер на странице входа rabota.by. Войдите руками.
2. **Сессия сохранена** — после ухода со `/login` cookies пишутся в `data/sessions/<profile>.storage.json` и в БД.
3. **Start search** — сбор вакансий, фильтры, категоризация, очередь в SQLite.
4. **Start apply** — отклики по очереди HIGH → MEDIUM → LOW с текстом из `letter_universal.txt`.
5. **Stop** — остановить текущий job.
6. Статус и журнал в UI обновляются примерно каждые 2 секунды.

## Конфигурация (.env)

```bash
cp -n .env.example .env
```

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | `sqlite:///./data/rabota_apply.sqlite` или будущий Postgres URL |
| `DATA_DIR` / `SESSIONS_DIR` | данные и файлы сессий |
| `LETTER_PATH` | универсальное сопроводительное письмо |
| `HEADLESS` | `false` — видимый браузер (удобно для логина) |
| `SEARCH_QUERIES` | поисковые запросы через запятую |
| `MAX_PER_HOUR` / `MAX_PER_DAY` | потолки откликов |
| `REQUIRE_REMOTE_OR_HYBRID` / `SKIP_GOV` / `REQUIRE_PYTHON_KEYWORDS` | фильтры |

Внешняя БД (заготовка):

```env
DATABASE_URL=postgresql+psycopg://user:SECRET@host:5432/rabota_apply
DB_PASSWORD=SECRET
```

Пока не-sqlite URL даёт `NotImplementedError` с подсказкой — порты уже абстрагированы.

## Версионирование через Poetry

Версия пакета задаётся в `pyproject.toml`:

```toml
[tool.poetry]
name = "autoapply"
version = "0.1.0"
```

Полезные команды:

```bash
poetry version          # текущая версия
poetry version patch    # 0.1.0 → 0.1.1
poetry version minor    # 0.1.0 → 0.2.0
poetry version major    # 0.1.0 → 1.0.0
poetry show             # установленные пакеты
poetry add <pkg>        # добавить зависимость
poetry add -G dev <pkg> # dev-зависимость
```

CLI entrypoint: `poetry run autoapply` → `app.main:run`.

## Структура (DDD)

```
.
├── app/
│   ├── main.py                 # FastAPI entrypoint
│   ├── domain/                 # сущности, enum, фильтры, categorize, ports
│   ├── application/            # use-cases (AppService), letter / rate-limit
│   ├── infrastructure/
│   │   ├── settings.py         # pydantic-settings / .env
│   │   ├── db/                 # SQLite UoW (порты → можно заменить)
│   │   └── browser/            # Playwright gateway + JobRunner
│   └── interfaces/
│       ├── api/                # HTTP API
│       └── web/                # templates + static UI
├── tests/
├── letter_universal.txt
├── pyproject.toml              # Poetry: зависимости и версия
├── poetry.lock
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

Слои:

| Слой | Роль |
|------|------|
| **domain** | бизнес-правила без FastAPI/Playwright: сущности, фильтры, категории fit, порты |
| **application** | сценарии: login / search / apply / stop, письмо, лимиты |
| **infrastructure** | SQLite, Playwright, settings из `.env` |
| **interfaces** | HTTP API и Web UI |

Порты репозиториев: `app/domain/ports.py`. Сейчас адаптер — SQLite. Для Postgres позже — тот же `UnitOfWork`, другой адаптер в `infrastructure/db/` + URL в `.env`.

## Категории fit и фильтры

| Категория | Смысл |
|-----------|--------|
| **HIGH** | python developer/разработчик в title + remote/hybrid + сильный стек |
| **MEDIUM** | есть python + remote/hybrid, но слабее title/сигналы |
| **LOW** | слабый/кривой матч |

До очереди: remote **или** hybrid; skip `*.gov.*`; keywords python/разработчик.  
Отклики идут HIGH → MEDIUM → LOW.

## Реализация: что важно

- **Playwright-сессия** — ручной логин, дальше `storage_state` на диске; воркер переиспользует cookies без повторного входа.
- **Rate limits** — `MIN_ACTION_INTERVAL`, `AFTER_APPLY_DELAY`, `JITTER`, `MAX_PER_HOUR` / `MAX_PER_DAY`.
- **Retry** — `LOAD_RETRIES` / `APPLY_RETRIES` с задержкой при загрузке страниц и отклике.
- **SQLite ports** — UoW скрывает хранилище; внешняя БД — смена адаптера, не переписывание UI/сервисов.
- **Один процесс** — UI, API и воркер в одном uvicorn-процессе; статусы `idle / logging_in / searching / applying / waiting_user / error / done`.

## Docker

```bash
cp -n .env.example .env
# в контейнере удобнее HEADLESS=true (уже в compose/Dockerfile)
docker compose up --build
```

UI: http://127.0.0.1:8080  
Данные монтируются в `./data`.

> Видимый браузер в Docker требует X11/VNC; для ручного логина удобнее локальный `poetry run uvicorn` с `HEADLESS=false`.  
> Если `poetry run playwright install chromium` падает с 403 (CDN недоступен в регионе) — VPN/зеркало или Docker-образ с уже установленным Chromium.

## API

| Method | Path | Действие |
|--------|------|----------|
| POST | `/api/login` | LoginSession |
| POST | `/api/login/confirm` | сохранить сессию |
| POST | `/api/search` | StartSearch |
| POST | `/api/apply` | StartApply |
| POST | `/api/stop` | StopJob |
| GET | `/api/status` | статус + stats |
| GET | `/api/stats` | статистика |
| GET | `/api/vacancies` | очередь |
| GET | `/api/logs` | журнал |
| GET | `/api/profiles` | профили |

Тело POST: `{"profile":"default"}`.
