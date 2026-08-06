# RABOTA_APPLY

Монолит для поиска и откликов на [rabota.by](https://rabota.by): Web UI + API + Playwright-воркер + локальная SQLite.  
Браузерная сессия (cookies / `storage_state`) — без OAuth `client_id`.

## Структура (DDD)

```
.
├── app/
│   ├── main.py                 # FastAPI entrypoint
│   ├── domain/                 # сущности, enum, фильтры, categorize, ports
│   ├── application/            # use-cases (AppService), letter/rate-limit
│   ├── infrastructure/
│   │   ├── settings.py         # pydantic-settings / .env
│   │   ├── db/                 # SQLite UoW (порты → swappable)
│   │   └── browser/            # Playwright gateway + JobRunner
│   └── interfaces/
│       ├── api/                # HTTP «ручки»
│       └── web/                # templates + static UI
├── tests/
├── letter_universal.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

Порты репозиториев: `app/domain/ports.py`. Сейчас — SQLite (`DATABASE_URL=sqlite:///...`).  
Для внешнего Postgres позже: тот же `UnitOfWork`, другой адаптер в `infrastructure/db/` + URL в `.env`.

## 10 принципов (продукт + UX)

1. **Simple** — один процесс, понятные кнопки.
2. **Responsive** — UI читается на телефоне и десктопе.
3. **Explicit statuses** — `idle / logging_in / searching / applying / waiting_user / error / done`.
4. **Local-first** — SQLite + файлы сессий на диске.
5. **Retry with backoff** — загрузка страниц и отклик с ретраями.
6. **Human-like rate limits** — паузы + jitter, лимиты час/сутки.
7. **Priority queues** — HIGH → MEDIUM → LOW.
8. **Transparent logs** — журнал событий в UI.
9. **Manual login, automated apply** — вход руками, отклик роботом с письмом.
10. **Stoppable jobs** — Stop в любой момент.

## Категории fit

| Категория | Смысл |
|-----------|--------|
| **HIGH** | python developer/разработчик в title + remote/hybrid + сильный стек |
| **MEDIUM** | есть python + remote/hybrid, но слабее title/сигналы |
| **LOW** | слабый/кривой матч |

Фильтры до очереди: remote **или** hybrid; skip `*.gov.*`; keywords python/разработчик.

## Конфигурация (.env)

```bash
cp .env.example .env
# отредактируйте .env — секреты только здесь
```

Ключевые переменные:

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | `sqlite:///./data/rabota_apply.sqlite` или будущий Postgres URL |
| `DATA_DIR` / `SESSIONS_DIR` | данные и `storage_state` |
| `LETTER_PATH` | универсальное сопроводительное |
| `HEADLESS` | `false` — видимый браузер (по умолчанию локально) |
| `SEARCH_QUERIES` | запросы через запятую |
| `MAX_PER_HOUR` / `MAX_PER_DAY` | потолки откликов |
| `REQUIRE_REMOTE_OR_HYBRID` / `SKIP_GOV` / `REQUIRE_PYTHON_KEYWORDS` | фильтры |

Внешняя БД позже:

```env
DATABASE_URL=postgresql+psycopg://user:SECRET@host:5432/rabota_apply
DB_PASSWORD=SECRET
```

Пока не-sqlite URL даст `NotImplementedError` с подсказкой — порты уже абстрагированы.

## Запуск локально

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env

# из корня репозитория:
uvicorn app.main:app --host 0.0.0.0 --port 8080
# или: python -m app.main
```

Откройте http://127.0.0.1:8080

Тесты:

```bash
pytest -q
```

## Docker

```bash
cp .env.example .env
# в Docker удобнее HEADLESS=true (уже в compose/Dockerfile)
docker compose up --build
```

UI: http://127.0.0.1:8080  
Данные монтируются в `./data`.

> Видимый браузер в Docker требует X11/VNC; для ручного логина удобнее локальный `uvicorn` с `HEADLESS=false`.

## Как пользоваться UI

1. **Профиль** — выберите или создайте (`default` уже есть).
2. **Login / Connect** — откроется браузер на странице входа rabota.by. Войдите руками.
3. **Сессия сохранена** — после входа нажмите (или дождитесь авто-детекта ухода с `/login`). Cookies → `data/sessions/<profile>.storage.json` + запись в БД.
4. **Start search** — сбор вакансий, фильтры, категоризация, очередь в SQLite.
5. **Start apply** — отклики по очереди HIGH→MEDIUM→LOW с `letter_universal.txt`.
6. **Stop** — остановить текущий job.
7. Статус-пилюля и журнал обновляются каждые ~2 с.

## API (ручки)

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
