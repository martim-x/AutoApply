# Fly.io (деплой) и GitHub Actions (только CI)

**GitHub Actions** ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) — только проверки: `poetry install` → `ruff` → `mypy app` → `pytest` на PR и push в `main`. Деплоя из Actions нет.

**Деплой** — отдельно:

- [Fly.io GitHub integration](https://fly.io/docs/launch/continuous-deployment-with-github/) (автодеплой из репозитория), или
- вручную: `fly deploy --app auto-apply-app`, или
- [Railway](./docker-railway.md) с подключением GitHub.

Конфиг приложения: [`fly.toml`](../fly.toml) (Dockerfile, порт **8080**, volume `/app/data`, **2 GB** RAM под Playwright).

---

## Одноразовая настройка Fly

```bash
# CLI: https://fly.io/docs/hands-on/install-flyctl/
brew install flyctl   # или curl -L https://fly.io/install.sh | sh
fly auth login

fly apps create auto-apply-app
# том для SQLite / sessions / reports (регион = primary_region в fly.toml)
fly volumes create auto_apply_app_data --region ams --size 3 --app auto-apply-app
```

Публичный URL после деплоя: **https://auto-apply-app.fly.dev** (если имя приложения свободно).

> **Уже есть приложение `autoapply` (или другое имя)?** Имя на Fly **нельзя** просто переименовать в `fly.toml` — нужно либо продолжать деплоить в существующий app (`fly deploy --app <старое-имя>` и поправить `app =` / `[[mounts]].source` под фактические имена), либо создать новый `auto-apply-app` и перенести volume/данные. Volume `autoapply_data` тоже остаётся со старым именем, пока не создадите новый `auto_apply_app_data`.

---

## Secrets на Fly (не коммитить)

Несекретные значения уже в `[env]` в `fly.toml` (`HEADLESS`, `DATA_DIR`, `DATABASE_URL`, …).

Секреты задаются на стороне Fly (не в GitHub Actions):

```bash
# Admin UI (/admin)
fly secrets set \
  ADMIN_USER='your_admin' \
  ADMIN_PASSWORD='strong_password' \
  ADMIN_SECRET="$(openssl rand -hex 32)" \
  --app auto-apply-app

# SMTP-алерты (пример Yandex)
fly secrets set \
  ALERT_SMTP_ENABLED=true \
  ALERT_SMTP_HOST=smtp.yandex.ru \
  ALERT_SMTP_PORT=465 \
  ALERT_SMTP_USER='you@example.com' \
  ALERT_SMTP_PASSWORD='app_password' \
  ALERT_SMTP_FROM='you@example.com' \
  ALERT_SMTP_TO='you@example.com' \
  ALERT_SMTP_TLS=true \
  --app auto-apply-app

# Расписания (по желанию)
fly secrets set \
  REPORT_SCHEDULE_ENABLED=true \
  REPORT_SCHEDULE_TIMEZONE=Europe/Minsk \
  PARSE_SCHEDULE_ENABLED=true \
  PARSE_SCHEDULE_TIMEZONE=Europe/Minsk \
  PARSE_SCHEDULE_TIMES=12:00,00:00 \
  --app auto-apply-app
```

То же можно сделать в [Fly dashboard](https://fly.io/dashboard) → приложение → **Secrets**.

Пароль из локального `.env` в git **не копировать**. Подставьте значения вручную.

Проверка: `fly secrets list --app auto-apply-app`

Локальный / ручной деплой:

```bash
fly deploy --app auto-apply-app
```

Логин в UI: **Войти (remote)** → screencast → **Сохранить сессию**. Данные живут на volume `/app/data`.

При первом старте с новым `DATABASE_URL=…/auto_apply_app.sqlite` приложение само переименует legacy `rabota_apply.sqlite` на volume, если новый файл ещё отсутствует.

---

## GitHub Actions (CI only)

| Событие | Что происходит |
|---------|----------------|
| PR / push в `main` | `poetry install` → `ruff` → `mypy app` → `pytest` |

Секрет `FLY_API_TOKEN` в GitHub Actions **не нужен** — Actions больше не вызывают `flyctl deploy`. Токен для автодеплоя настраивается в интеграции Fly ↔ GitHub (или вы деплоите вручную через CLI).

---

## Важно

- Одна машина / один volume с SQLite — не масштабируйте реплики на общий файл.
- `min_machines_running = 1` и `auto_stop_machines = off` — чтобы работали parse/report schedules.
- Launch-профиль: положите `config/launch.json` через volume/SSH или соберите свой слой; в образе есть только `launch.example.json`.
- Railway по-прежнему описан в [docker-railway.md](./docker-railway.md).
