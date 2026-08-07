# Docker (локально) и Railway (один сервис)

Chromium **внутри образа** Playwright — хостовый браузер не нужен.

Прод-деплой — **Fly.io** ([fly-io.md](./fly-io.md): `fly.toml`, GitHub integration или `fly deploy`) либо этот Railway-гайд. GitHub Actions — только CI (тесты), без деплоя.

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
ADMIN_SECRET=long_random_string   # ./scripts/gen_admin_secret.sh
```

Полезно:

```env
DATA_DIR=/app/data
DATABASE_URL=sqlite:////app/data/auto_apply_app.sqlite
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

Парсинг по расписанию (тот же процесс uvicorn): при наличии сессий запускает **HH search и LinkedIn vacancy collect параллельно** (два Chromium, если оба слота свободны). Дубликаты по URL/`vacancy_id` пропускаются; при сортировке по дате — early-stop после `PARSE_OLD_STREAK_STOP` подряд уже известных вакансий.

> **RAM:** два Chromium на профиль ≈ 2× память headless Chrome. На Railway держите запас (часто 1–2 GB+), особенно если одновременно открыт remote screencast.

4. **Volume** на `/app/data` — иначе SQLite cookies/PDF пропадут после редеплоя
   (для **Postgres** volume на БД не нужен — данные в отдельном Postgres-сервисе;
   volume всё ещё нужен для Playwright sessions / PDF: `/app/data`).
   При первом старте на пустом volume приложение само создаёт пустой SQLite со схемой
   (копировать локальную БД не нужно). Чтобы сбросить данные: удалить файл на volume
   или один раз выставить `RESET_DB=true`, перезапустить и снова выключить.

### Postgres на Railway (отдельный сервис БД)

1. Add Plugin / New → **PostgreSQL**.
2. В web-сервисе Variables: ссылка на `DATABASE_URL` из Postgres
   (`${{Postgres.DATABASE_URL}}` или скопированный URL).
3. Приложение само нормализует `postgresql://…` → `postgresql+psycopg://…`
   и создаёт таблицы (те же порты UnitOfWork, что у SQLite).
4. SQLite-пути (`sqlite:////app/data/...`) больше не используй, если перешёл на PG.
5. Healthcheck по-прежнему `GET /api/health`.
5. Deploy → публичный URL → UI.
6. Логин: **Войти (remote)** / LinkedIn → screencast → **Сохранить сессию**.
7. `/admin` — редактор `.env` (нужны `ADMIN_*`). После Save — **Restart**.

Railway `PORT` подхватывается CMD: `uvicorn … --port ${PORT:-8080}`.

Не запускайте несколько реплик с одним SQLite-файлом.

---

## Что лежит в `/app/data`

| Путь | Назначение |
|------|------------|
| `auto_apply_app.sqlite` | очередь HH, контакты/вакансии LinkedIn, журнал (legacy `rabota_apply.sqlite` переименовывается при старте) |
| `sessions/<profile>.storage.json` | cookies rabota/hh |
| `sessions/<profile>.linkedin.storage.json` | cookies LinkedIn |
| `reports/*.pdf` | сохранённые / по расписанию PDF |

См. также [linkedin.md](./linkedin.md), [getting-started.md](./getting-started.md).
