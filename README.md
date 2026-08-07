# auto-apply

Личный монолит для поиска вакансий и автооткликов на **rabota.by / hh.ru**: Web UI, REST API, Playwright-воркер, SQLite.

Скоринг и фильтры заточены под профиль из Obsidian **`07 Legend`** (Middle+ Python, FastAPI/Django, remote/hybrid, вилка **$2200–2800**).

Сессия — ручной логин в браузере → cookies / `storage_state` (без OAuth API).

---

## Документация

| Документ | О чём |
|----------|--------|
| **[docs/getting-started.md](docs/getting-started.md)** | На что рассчитан запуск · установка · launch-профиль · Docker |
| **[docs/user-guide.md](docs/user-guide.md)** | Как пользоваться UI (login → search → apply, Explain, тема) |
| **[docs/architecture.md](docs/architecture.md)** | Техрешения: DDD, Playwright, scoring, remote browser |
| **[docs/alerts.md](docs/alerts.md)** | SMTP-алерты (captcha/error) и durability прогона |
| **[docs/fly-io.md](docs/fly-io.md)** | Fly.io деплой, volume, secrets; GitHub Actions = только CI |
| **[docs/priorities.md](docs/priorities.md)** | Legend → фильтры и дерево весов |

---

## Быстрый старт

```bash
poetry install
unset PLAYWRIGHT_BROWSERS_PATH
poetry run playwright install chromium
cp -n .env.example .env
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

UI: http://127.0.0.1:8080  

Тесты: `poetry run pytest -q`

Дальше по чеклисту: [getting-started.md](docs/getting-started.md) → [user-guide.md](docs/user-guide.md).

---

## Возможности (кратко)

- Launch-профиль: site + город + queries + вилка + level
- Фильтры: remote/hybrid, skip gov, python-keywords, location, optional salary_strict
- Weight-graph → HIGH / MEDIUM / LOW + кнопка **Explain**
- Очередь откликов HIGH → MEDIUM → LOW, письмо из `letter_universal.txt`
- Тема system / light / dark, mobile layout, SVG-иконки
- Remote browser (CDP screencast) для логина на Railway/Docker
- Rate limits, retry, Stop текущего job

---

## Конфигурация

| Что | Где |
|-----|-----|
| Env / лимиты | `.env` ← `.env.example` |
| Прогон поиска | `config/launch.json` (пример: `launch.example.json`) |
| Веса fit | `config/weights.json` |
| Города → area | `config/areas.json` |
| Письмо | `letter_universal.txt` |
| Данные | `data/` (sqlite + sessions) |

`launch.json` и `.env` в git не коммитятся.

---

## Структура

```
app/
  domain/           # фильтры, scoring, launch_profile, ports
  application/      # use-cases
  infrastructure/   # settings, sqlite, Playwright, remote CDP
  interfaces/       # API + Web UI
config/
docs/
tests/
```

Слои и решения — в [architecture.md](docs/architecture.md).

---

## Docker / Railway / Fly.io

```bash
cp -n .env.example .env
docker compose up --build
```

Образ ставит **Playwright Chromium** (`HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true`). Данные — том `./data` (на Fly/Railway — volume на `/app/data`).

**CI:** push/PR в `main` → ruff + mypy + pytest (`.github/workflows/ci.yml`). Деплоя из Actions нет.

**Деплой:** Fly.io GitHub integration или `fly deploy` вручную (`fly.toml`); либо Railway с GitHub connect. Секреты приложения — `fly secrets set …` / Fly dashboard (не `FLY_API_TOKEN` в GitHub Actions). См. **[docs/fly-io.md](docs/fly-io.md)**.

**Railway:** Deploy `Dockerfile` → Variables: `HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true`, плюс `ADMIN_USER` / `ADMIN_PASSWORD` / `ADMIN_SECRET` → volume `/app/data` → логин через remote screencast в UI. Редактор `.env`: `/admin` (если `ADMIN_*` заданы; иначе 404). Подробнее — [docs/docker-railway.md](docs/docker-railway.md), [docs/getting-started.md](docs/getting-started.md).

---

## API

Тело POST обычно: `{"profile":"default"}`.

| Method | Path | Действие |
|--------|------|----------|
| POST | `/api/login` | Login (local или remote) |
| POST | `/api/login/confirm` | Сохранить сессию |
| POST | `/api/remote-browser/start` | Старт screencast |
| POST | `/api/remote-browser/save` | Сохранить `storage_state` |
| POST | `/api/remote-browser/stop` | Стоп remote |
| GET | `/api/remote-browser/status` | Статус remote |
| WS | `/api/remote-browser/ws?profile=` | Кадры + ввод |
| POST | `/api/search` | Поиск |
| POST | `/api/apply` | Отклики |
| POST | `/api/stop` | Stop job |
| GET | `/api/status` | Статус + stats |
| GET | `/api/stats` | Статистика |
| GET | `/api/vacancies` | Очередь |
| GET | `/api/vacancies/explain` | Explain score |
| GET | `/api/logs` | Журнал |
| GET | `/api/profiles` | Профили |
| GET/POST | `/api/launch*` | Launch-профиль |

---

## Poetry

Версия в `pyproject.toml`. CLI: `poetry run autoapply`.  
`requirements.txt` — экспорт для Docker; источник правды — `poetry.lock`.
