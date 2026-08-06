# AutoApply (RABOTA_APPLY)

Монолит для поиска вакансий и автоматических откликов на [rabota.by](https://rabota.by): Web UI, REST API, Playwright-воркер и локальная SQLite.  
Один профиль, ручной логин в браузере, дальше — поиск и отклики роботом. Сессия хранится как cookies / `storage_state` (без OAuth `client_id`).

## Возможности

- Web UI и API в одном процессе FastAPI (светлая тема, mobile-first)
- Ручной вход → сохранение Playwright-сессии → поиск → очередь → отклики
- **Weight-graph scoring**: декларативные веса `config/weights.json` → HIGH / MEDIUM / LOW + Explain
- Фильтры: remote или hybrid, пропуск `*.gov.*`, ключевые слова python/разработчик
- Human-like rate limits (паузы, jitter, лимиты час/сутки) и retry с backoff
- Stop текущего job в любой момент
- Remote browser (CDP screencast) для логина на Railway
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

# 2) Браузер Playwright (если Cursor выставил PLAYWRIGHT_BROWSERS_PATH — сбросьте)
unset PLAYWRIGHT_BROWSERS_PATH
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

1. **Login / Connect** — локально откроется окно Chromium на странице входа rabota.by (если remote browser выключен). Войдите руками.
2. **Сессия сохранена** — после ухода со `/login` cookies пишутся в `data/sessions/<profile>.storage.json` и в БД.
3. **Start search** — сбор вакансий, фильтры, категоризация, очередь в SQLite.
4. **Start apply** — отклики по очереди HIGH → MEDIUM → LOW с текстом из `letter_universal.txt`.
5. **Stop** — остановить текущий job.
6. Статус и журнал в UI обновляются примерно каждые 2 секунды.

### Remote browser / Login в Web UI (Railway и headless)

Интерактивный screencast серверного Chromium прямо во вкладке UI (CDP `Page.startScreencast` → JPEG по WebSocket, мышь/клавиатура → Playwright). Нужен для логина на деплое без X11/VNC.

```bash
# .env
ENABLE_REMOTE_BROWSER=true
HEADLESS=true          # на Railway/Docker почти всегда так
REMOTE_BROWSER_JPEG_QUALITY=55   # ниже = меньше трафика, чуть хуже картинка
```

**Локально (Poetry):**

```bash
cp -n .env.example .env
# в .env: ENABLE_REMOTE_BROWSER=true
poetry run playwright install chromium
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

1. Откройте http://127.0.0.1:8080  
2. Нажмите **Открыть браузер / Login** (или **Login (remote)**).  
3. В модалке появится картинка серверного Chromium — войдите на rabota.by кликами/клавиатурой.  
4. **Сессия сохранена** (в модалке или в панели) → `storage_state` на диск.  
5. **Закрыть** / **Stop** — остановить remote-сессию. Дальше Search / Apply как обычно.

**Railway / Docker:** в образе уже `HEADLESS=true` и `ENABLE_REMOTE_BROWSER=true`. Откройте публичный URL сервиса и тот же click-through. Латентность screencast/ввода обычно **0.2–2 с** (регион, JPEG quality, CPU) — для логина нормально.

Fallback (если screencast не подходит): noVNC/Xvfb вокруг того же Chromium — не входит в MVP; текущий путь — CDP screencast без отдельного VNC.

## Конфигурация (.env)

```bash
cp -n .env.example .env
```

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | `sqlite:///./data/rabota_apply.sqlite` или будущий Postgres URL |
| `DATA_DIR` / `SESSIONS_DIR` | данные и файлы сессий |
| `LETTER_PATH` | универсальное сопроводительное письмо |
| `HEADLESS` | `false` — видимый браузер (локальный логин); на Railway — `true` |
| `ENABLE_REMOTE_BROWSER` | `true` — логин через embedded screencast в UI |
| `REMOTE_BROWSER_JPEG_QUALITY` | качество JPEG кадров (по умолчанию `55`) |
| `REMOTE_BROWSER_EVERY_NTH_FRAME` | слать каждый N-й кадр CDP (по умолчанию `1`) |
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
| **infrastructure** | SQLite, Playwright, remote CDP session, settings из `.env` |
| **interfaces** | HTTP API, WebSocket screencast, Web UI |

Порты репозиториев: `app/domain/ports.py`. Сейчас адаптер — SQLite. Для Postgres позже — тот же `UnitOfWork`, другой адаптер в `infrastructure/db/` + URL в `.env`.

## Категории fit и фильтры

| Категория | Смысл |
|-----------|--------|
| **HIGH** | сильный суммарный вес Legend-сигналов (Python-роль, FastAPI/Django, remote/hybrid, стек) |
| **MEDIUM** | частичный матч |
| **LOW** | доминируют минусы (офис-only, gov, чужой стек) или мало плюсов |

До очереди: remote **или** hybrid; skip `*.gov.*`; keywords python/разработчик.  
Отклики идут HIGH → MEDIUM → LOW.

### Weight graph (как править веса)

Файл: [`config/weights.json`](config/weights.json).

- Каждый сигнал: `weight` в диапазоне **0..+1** (плюс) или **0..−1** (минус), плюс `patterns` (regex).
- Движок: `app/domain/scoring/` — суммирует сработавшие веса, нормализует в score 0..100, режет порогами `thresholds.high` / `thresholds.medium`.
- Сигналы заточены под Legend (Middle+ Python, FastAPI/Django, очереди, Postgres, remote/hybrid, вилка).
- После правки JSON перезапустите uvicorn (кэш карты сбрасывается при рестарте; либо `reload_weight_map()`).

В UI у каждой вакансии кнопка **Explain** — текст из шаблонов + топ плюсов/минусов (`GET /api/vacancies/explain?vacancy_id=`).

### Mobile UI

Breakpoints: `<640` телефон (карточки вакансий, 2 колонки кнопок), `640+` шире, `860+` таблица + две панели. Кнопки ≥44px, статус по центру на узких экранах, журнал фиксированной высоты со скроллом.

## Реализация: что важно

- **Playwright-сессия** — ручной логин (локальное окно или remote screencast в UI), дальше `storage_state` на диске; воркер переиспользует cookies без повторного входа.
- **Remote browser** — `RemoteBrowserManager` (infrastructure) + use-case в `AppService` + WS `/api/remote-browser/ws`.
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

> Для ручного логина в Docker/Railway включите `ENABLE_REMOTE_BROWSER=true` (по умолчанию в compose/Dockerfile) и войдите через UI.  
> Локально без remote: `HEADLESS=false` и обычный **Login / Connect**.  
> Если `poetry run playwright install chromium` падает с 403 (CDN недоступен в регионе) — VPN/зеркало или Docker-образ с уже установленным Chromium.

## API

| Method | Path | Действие |
|--------|------|----------|
| POST | `/api/login` | LoginSession (local или remote, если `ENABLE_REMOTE_BROWSER`) |
| POST | `/api/login/confirm` | сохранить сессию |
| POST | `/api/remote-browser/start` | старт remote Chromium + screencast |
| POST | `/api/remote-browser/save` | сохранить `storage_state` |
| POST | `/api/remote-browser/stop` | остановить remote (`save` optional) |
| GET | `/api/remote-browser/status` | статус remote-сессии |
| WS | `/api/remote-browser/ws?profile=` | JPEG-кадры + mouse/key JSON |
| POST | `/api/search` | StartSearch |
| POST | `/api/apply` | StartApply |
| POST | `/api/stop` | StopJob (в т.ч. remote browser) |
| GET | `/api/status` | статус + stats + remote_browser |
| GET | `/api/stats` | статистика |
| GET | `/api/vacancies` | очередь |
| GET | `/api/vacancies/explain` | weight-graph Explain (`vacancy_id`) |
| GET | `/api/logs` | журнал |
| GET | `/api/profiles` | профили |

Тело POST: `{"profile":"default"}`.
