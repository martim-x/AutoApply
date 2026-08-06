# Docker (локально) и Railway (один сервис)

Chromium **внутри образа** Playwright — хостовый браузер не нужен.

---

## Локально: Docker Compose

```bash
cp -n .env.example .env
# для контейнера удобно:
# HEADLESS=true
# ENABLE_REMOTE_BROWSER=true

docker compose up --build
```

UI: **http://127.0.0.1:8080**

| Что | Где |
|-----|-----|
| Порт | `8080` (или `PORT` на хосте) |
| Данные | том `./data` → `/app/data` (SQLite, `sessions/`, `reports/`) |
| Конфиг | `./config` → `/app/config` (`launch.json`, `linkedin.launch.json`) |
| Env | `.env` смонтирован (удобно для `/admin`) |

В образе по умолчанию: `HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true`, `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`.

Healthcheck бьёт в `GET /api/health`.

Остановка: `Ctrl+C` или `docker compose down`.

---

## Railway: один сервис из Dockerfile

Ограничение продукта: **один контейнер** = Web UI + Playwright jobs + планировщик PDF в том же процессе uvicorn.

1. New Project → Deploy from GitHub (или Docker).
2. Root = корень репо; билдер берёт `Dockerfile` (`mcr.microsoft.com/playwright/python` + Chromium).
3. **Variables** (минимум):

```env
HEADLESS=true
ENABLE_REMOTE_BROWSER=true
ADMIN_USER=your_admin
ADMIN_PASSWORD=strong_password
ADMIN_SECRET=long_random_string
```

Полезно:

```env
DATA_DIR=/app/data
DATABASE_URL=sqlite:////app/data/rabota_apply.sqlite
REPORT_SCHEDULE_ENABLED=true
REPORT_SCHEDULE_TIMEZONE=Europe/Minsk
REPORT_SCHEDULE_HOUR=4
REPORT_SCHEDULE_MINUTE=0
REPORT_SCHEDULE_KIND=work
REPORT_SCHEDULE_PROFILE=default

# Vacancy parse twice daily (noon + midnight, Europe/Minsk)
PARSE_SCHEDULE_ENABLED=true
PARSE_SCHEDULE_TIMEZONE=Europe/Minsk
PARSE_SCHEDULE_TIMES=12:00,00:00
PARSE_SCHEDULE_PROFILE=default
PARSE_EARLY_STOP_ENABLED=true
PARSE_OLD_STREAK_STOP=5
```

Парсинг по расписанию (тот же процесс uvicorn): при наличии сессий запускает **HH search и LinkedIn vacancy collect** (оба, если оба есть). Дубликаты по URL/`vacancy_id` пропускаются; при сортировке по дате — early-stop после `PARSE_OLD_STREAK_STOP` подряд уже известных вакансий.

4. **Volume** на `/app/data` — иначе SQLite, cookies и PDF пропадут после редеплоя.
5. Deploy → публичный URL → UI.
6. Логин: **Войти (remote)** / LinkedIn → screencast → **Сохранить сессию**.
7. `/admin` — редактор `.env` (нужны `ADMIN_*`). После Save — **Restart**.

Railway `PORT` подхватывается CMD: `uvicorn … --port ${PORT:-8080}`.

Не запускайте несколько реплик с одним SQLite-файлом.

---

## Что лежит в `/app/data`

| Путь | Назначение |
|------|------------|
| `rabota_apply.sqlite` | очередь HH, контакты/вакансии LinkedIn, журнал |
| `sessions/<profile>.storage.json` | cookies rabota/hh |
| `sessions/<profile>.linkedin.storage.json` | cookies LinkedIn |
| `reports/*.pdf` | сохранённые / по расписанию PDF |

См. также [linkedin.md](./linkedin.md), [getting-started.md](./getting-started.md).
