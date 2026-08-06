# Fly.io + GitHub Actions (CI/CD)

Деплой из GitHub: **ruff → mypy → pytest**, затем `flyctl deploy` на push в `main`.

Конфиг приложения: [`fly.toml`](../fly.toml) (Dockerfile, порт **8080**, volume `/app/data`, **2 GB** RAM под Playwright).

---

## Одноразовая настройка Fly

```bash
# CLI: https://fly.io/docs/hands-on/install-flyctl/
brew install flyctl   # или curl -L https://fly.io/install.sh | sh
fly auth login

fly apps create autoapply
# том для SQLite / sessions / reports (регион = primary_region в fly.toml)
fly volumes create autoapply_data --region ams --size 3 --app autoapply
```

Публичный URL после деплоя: **https://autoapply.fly.dev** (если имя приложения свободно).

---

## Secrets на Fly (не коммитить)

Несекретные значения уже в `[env]` в `fly.toml` (`HEADLESS`, `DATA_DIR`, `DATABASE_URL`, …).

Секреты — только через CLI:

```bash
# Admin UI (/admin)
fly secrets set \
  ADMIN_USER='your_admin' \
  ADMIN_PASSWORD='strong_password' \
  ADMIN_SECRET="$(openssl rand -hex 32)" \
  --app autoapply

# SMTP-алерты (пример Yandex)
fly secrets set \
  ALERT_SMTP_ENABLED=true \
  ALERT_SMTP_HOST=smtp.yandex.ru \
  ALERT_SMTP_PORT=465 \
  ALERT_SMTP_USER='you@yandex.ru' \
  ALERT_SMTP_PASSWORD='app_password' \
  ALERT_SMTP_FROM='you@yandex.ru' \
  ALERT_SMTP_TO='you@yandex.ru' \
  ALERT_SMTP_TLS=true \
  --app autoapply

# Расписания (по желанию)
fly secrets set \
  REPORT_SCHEDULE_ENABLED=true \
  REPORT_SCHEDULE_TIMEZONE=Europe/Minsk \
  PARSE_SCHEDULE_ENABLED=true \
  PARSE_SCHEDULE_TIMEZONE=Europe/Minsk \
  PARSE_SCHEDULE_TIMES=12:00,00:00 \
  --app autoapply
```

Пароль из локального `.env` в git **не копировать**. Подставьте значения вручную.

Проверка: `fly secrets list --app autoapply`

Локальный деплой:

```bash
fly deploy --app autoapply
```

Логин в UI: **Войти (remote)** → screencast → **Сохранить сессию**. Данные живут на volume `/app/data`.

---

## GitHub Actions: `FLY_API_TOKEN`

1. Создайте deploy-токен (предпочтительно):

```bash
fly tokens create deploy -x 999999h --app autoapply
```

Либо org/account token в [Fly dashboard → Tokens](https://fly.io/dashboard).

2. В репозитории GitHub → **Settings → Secrets and variables → Actions** → New repository secret:

| Name | Value |
|------|--------|
| `FLY_API_TOKEN` | вывод `fly tokens create deploy …` |

Без этого секрета job **Deploy to Fly.io** упадёт после зелёного CI.

Workflow: [`.github/workflows/ci-cd.yml`](../.github/workflows/ci-cd.yml)

| Событие | Что происходит |
|---------|----------------|
| PR / push в `main` | `poetry install` → `ruff` → `mypy app` → `pytest` |
| push в `main` (после CI) | `flyctl deploy --remote-only` |

---

## Важно

- Одна машина / один volume с SQLite — не масштабируйте реплики на общий файл.
- `min_machines_running = 1` и `auto_stop_machines = off` — чтобы работали parse/report schedules.
- Launch-профиль: положите `config/launch.json` через volume/SSH или соберите свой слой; в образе есть только `launch.example.json`.
- Railway по-прежнему описан в [docker-railway.md](./docker-railway.md).
