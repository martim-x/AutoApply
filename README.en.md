# AutoApply

**Language:** English (this file) · [Русский](README.md)

Personal monolith for job search and auto-apply on rabota.by, hh.ru, and LinkedIn. One process: Web UI, REST API, Playwright worker, and a database (SQLite by default, Postgres when you choose it).

Deeper notes live under [`docs/`](docs/) (mostly Russian). This README is the bilingual canon: why the product exists, what it offers, what it runs on, which decisions are fixed, and how to run it locally or on a PaaS.

---

## 1. About the project

AutoApply covers the daily loop of a Middle+ Python candidate (profile from Obsidian `07 Legend`): find relevant vacancies, drop noise with hard filters, score fit with a weight graph, apply in HIGH → MEDIUM → LOW order, and optionally grow a LinkedIn network.

Site sessions come from a manual browser login and a saved Playwright `storage_state` (cookies). Official HH OAuth returned `geo_forbidden` for BY, so the project stayed on the browser path. LinkedIn is UI automation only as well.

| Question | Answer |
|----------|--------|
| Audience | One owner, several named profiles (separate sessions and queues) |
| What it does | Search and apply on rabota.by / hh.ru; LinkedIn networking and vacancy link collection |
| Data | SQLite under `data/` or Postgres via `DATABASE_URL`; sessions and PDFs beside the DB |
| What it is not | Public multi-tenant SaaS, a company ATS, 2FA/captcha bypass, LLM ranking |

Typical day: start the service → check launch criteria → Login → Search → review the queue and Explain → Apply (start with `dry_run: true`).

---

## 2. Features

| Area | What you get |
|------|----------------|
| HH launch profile | Site, country, city, queries, remote/hybrid, skip gov, python keywords, USD salary band, level, limits, dry_run |
| Filters | Binary pass/fail before queueing (office-only, gov, other city when `strict`, salary_strict) |
| Scoring | Weight tree in `config/weights.json` → score 0-100 → HIGH / MEDIUM / LOW + Explain in the UI |
| Apply queue | Order HIGH → MEDIUM → LOW; cover letter from `letters/` (`LETTER_STYLE`) |
| LinkedIn workspace | Separate tab: Connect via people search, collect vacancy links, own `linkedin.launch.json` |
| Remote browser | CDP screencast in a UI modal (login on Docker / Railway / Fly without a host GUI) |
| Profiles | Multiple profiles with isolated HH and LinkedIn sessions |
| Schedules | PDF report and vacancy parse twice a day in the same uvicorn process |
| Alerts | SMTP on captcha / error / parse-fail with rate limiting |
| UI | Jinja + vanilla JS/CSS; system / light / dark theme; mobile layout; queue and journal panels |
| Access control | Owner gate at `/login` and Admin at `/admin` when `ADMIN_*` / `GATE_*` are set |
| Job control | Start search / apply / LinkedIn actions; Stop the current slot |

---

## 3. Tech stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.11-3.14 (`requires-python` in `pyproject.toml`; CI uses 3.12) |
| Packaging | Poetry (`pyproject.toml` + `poetry.lock`); `requirements.txt` is an export for Docker |
| Web / API | FastAPI, Uvicorn, Jinja2, Starlette sessions, PyJWT |
| Browser | Playwright Chromium (image `mcr.microsoft.com/playwright/python`) |
| Remote UI | CDP `Page.startScreencast` → JPEG over WebSocket |
| Database | SQLite by default; Postgres via SQLAlchemy + psycopg3 |
| Reports | ReportLab (PDF) |
| Config | pydantic-settings from `.env`; launch JSON / text DSL |
| Container | Multi-stage `Dockerfile`, `docker-compose.yml` |
| PaaS | Fly.io (`fly.toml`) and Railway (Deploy from Dockerfile; no `railway.toml` / Procfile in this repo) |
| CI | GitHub Actions: ruff + mypy + pytest on push/PR to `main` (Actions do not deploy) |

---

## 4. Architecture and ADRs

There are no formal `ADR-001`-style files. Fixed decisions live in [`docs/architecture.md`](docs/architecture.md) and the related guides. The table below is the short map of context → choice → outcome.

### Layers (DDD monolith)

```
interfaces  →  application  →  domain
                  ↑
            infrastructure
```

| Layer | Responsibility | Where |
|-------|----------------|-------|
| domain | Filters, scoring, launch/linkedin profile, ports | `app/domain/` |
| application | Use-cases: login, search, apply, explain, alerts, reports | `app/application/` |
| infrastructure | Settings, SQLite/Postgres UoW, Playwright, remote CDP, schedulers, SMTP | `app/infrastructure/` |
| interfaces | HTTP, WebSocket, Jinja UI, owner gate, admin | `app/interfaces/` |

### Key decisions

| Decision | Context | Outcome | Doc / code |
|----------|---------|---------|------------|
| Single FastAPI process | Personal tool; job status in one place | Web + API + worker + scheduler in uvicorn | `app/main.py` |
| Browser session instead of HH OAuth | BY hit `geo_forbidden` | Manual login → `storage_state` on disk | `docs/architecture.md` §2 |
| Launch.json as run source | One artifact for “how I search today” | Overrides `.env` for site/area/queries/filters | `app/domain/launch_profile.py` |
| Filter, then score | Office-only and gov should leave the queue empty | Pass/fail first, then weight-graph | `filters.py`, `scoring/` |
| Remote screencast | PaaS has no usable host GUI | CDP JPEG + input in a modal | `remote_session.py` |
| Two Chromium slots per profile | HH and LinkedIn in parallel | `profile:hh` and `profile:linkedin` | `docs/linkedin.md` |
| SQLite by default | Zero-ops locally | File under `data/`; Postgres optional | `docs/docker-railway.md` |
| CI without deploy | Checks separate from shipping | Actions only lint/test; deploy via CLI / Fly GitHub integration / Railway | `docs/fly-io.md` |

### Directory map

```
app/
  domain/           # rules and ports
  application/      # use-cases
  infrastructure/   # DB, browser, settings, alerts, schedulers
  interfaces/       # API, Web UI, auth, admin
config/             # areas, weights, launch*.example.json
data/               # sqlite, sessions, reports (do not commit secrets)
docs/               # deeper guides
tests/
letters/              # cover letter templates (3 styles)
letter_universal.txt  # legacy single-file LETTER_PATH
```

Further reading:

| Document | Topic |
|----------|--------|
| [docs/architecture.md](docs/architecture.md) | Full decision write-up |
| [docs/getting-started.md](docs/getting-started.md) | Purpose and first bring-up |
| [docs/user-guide.md](docs/user-guide.md) | Step-by-step UI |
| [docs/linkedin.md](docs/linkedin.md) | LinkedIn workspace |
| [docs/docker-railway.md](docs/docker-railway.md) | Docker Compose and Railway |
| [docs/fly-io.md](docs/fly-io.md) | Fly.io and CI boundaries |
| [docs/alerts.md](docs/alerts.md) | SMTP and run durability |
| [docs/priorities.md](docs/priorities.md) | Legend → filters and weights |

Job statuses: `idle` → `logging_in` / `waiting_user` → `searching` → `applying` → `done` | `error`. Stop cancels the current slot (and the remote browser when needed).

---

## 5. Usage guide

### 5.1. Requirements

| Item | Note |
|------|------|
| OS | macOS / Linux (Windows at your own risk; Playwright is supported) |
| Python | 3.11-3.14 |
| Poetry | 2.x (Docker and CI pin 2.1.3) |
| Browser | Chromium via `poetry run playwright install chromium` |

### 5.2. Local deployment

Context: you are at the repo root and want a visible Chromium for login plus the UI on your machine.

```bash
poetry install

# If the environment set a sandbox browser path (Cursor and similar), clear it
unset PLAYWRIGHT_BROWSERS_PATH
poetry run playwright install chromium

cp -n .env.example .env
# First run can keep the defaults

poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
# or: poetry run autoapply
```

| Step | Detail |
|------|--------|
| UI | http://127.0.0.1:8080 |
| Port | `PORT` in `.env` (default 8080); the uvicorn command above also binds 8080 |
| Tests | `poetry run pytest -q` |
| Playwright “Executable doesn't exist” | Run `unset PLAYWRIGHT_BROWSERS_PATH` again and `poetry run playwright install chromium` |

Recommended values for a local headed browser:

```env
HEADLESS=false
ENABLE_REMOTE_BROWSER=false
```

Config to check before the first Search:

| Path | Purpose |
|------|---------|
| `.env` | Secrets and overrides (from `.env.example`) |
| `config/launch.json` | HH run profile (example: `config/launch.example.json`; gitignored) |
| `config/linkedin.launch.json` | LinkedIn criteria (example: `linkedin.launch.example.json`) |
| `config/areas.json` | Country/city catalog → HH `area_id` |
| `config/weights.json` | Scoring weight tree |
| `letters/` | Cover letter templates (impact / responsibility / project) |
| `data/` | SQLite, `sessions/`, `reports/` (created on startup) |

If `launch.json` is missing, the service falls back to the example file or `.env` defaults.

#### Local Docker Compose

```bash
cp -n .env.example .env
docker compose up --build
```

| Item | Detail |
|------|--------|
| UI | http://127.0.0.1:8080 |
| Data | volume `./data` → `/app/data` |
| Config | `./config` → `/app/config` |
| Container env | `HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true` (hardcoded in compose, even when the host `.env` says otherwise) |
| Healthcheck | `GET /api/health` |

### 5.3. Environment variables

Source of truth: [`.env.example`](.env.example) and `app/infrastructure/settings.py`. The service **starts without required secrets**: a default `.env` is enough for local UI and SQLite. Secrets matter for the owner gate, admin, SMTP, and production cookies.

“Required” below means “you must set this on purpose for that scenario.” For a cold local start, every row is optional.

#### App and paths

| Variable | Required | Default / example | Meaning |
|----------|----------|-------------------|---------|
| `APP_NAME` | no | `auto-apply-app` | App title (FastAPI) |
| `HOST` | no | `0.0.0.0` | Bind address |
| `PORT` | no | `8080` | Port (Railway injects `PORT` into the image CMD) |
| `DEBUG` | no | `false` | Debug flag |
| `DATA_DIR` | no | `./data` | Data root |
| `SESSIONS_DIR` | no | `./data/sessions` | Playwright cookies (optional to set) |
| `LETTER_PATH` | no | `./letters` | Letter file or directory of `*.txt` |
| `LETTER_STYLE` | no | `rotate` | `rotate` / `impact` / `responsibility` / `project` |
| `LAUNCH_PATH` | no | `./config/launch.json` | HH launch profile |
| `LINKEDIN_LAUNCH_PATH` | no | `./config/linkedin.launch.json` | LinkedIn launch |

#### Database

| Variable | Required | Example | Meaning |
|----------|----------|---------|---------|
| `DATABASE_URL` | no* | `sqlite:///./data/auto_apply_app.sqlite` | Default SQLite. Empty volume → file and schema created on startup. Legacy `rabota_apply.sqlite` is renamed if needed |
| `DATABASE_URL` (Postgres) | no* | `postgresql://user:pass@host:5432/railway` or `postgresql+psycopg://…` | Same UnitOfWork; app normalizes `postgresql://` → `postgresql+psycopg://` |
| `DB_PASSWORD` | no | (empty) | Reserved; password usually lives in the URL |
| `RESET_DB` | no | `false` | Set `true` once to wipe SQLite / drop Postgres public schema, then set back to `false` |

\* A valid DB is required for work. The default SQLite path covers a local start with no edits.

#### HH search defaults (overridden by `launch.json`)

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `BASE_URL` | no | `https://rabota.by` | Base site |
| `SEARCH_AREA` | no | `16` | Fallback area |
| `SEARCH_QUERIES` | no | comma-separated python queries | SERP queries |
| `VACANCY_LIMIT` | no | `30` | Vacancies to parse per search |
| `APPLY_LIMIT` | no | `30` | Queued items to process per apply |
| `DRY_RUN` | no | `false` | Skip the real Apply click |
| `REQUIRE_REMOTE_OR_HYBRID` | no | `true` | Format filter |
| `SKIP_GOV` | no | `true` | Drop gov |
| `REQUIRE_PYTHON_KEYWORDS` | no | `true` | Require python/developer signal |

#### Browser and remote screencast

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `HEADLESS` | no | `false` locally; `true` in Docker/Fly image | No host GUI |
| `ENABLE_REMOTE_BROWSER` | for headless PaaS: yes | `false` | Embedded screencast; when `true`, code forces headless |
| `REMOTE_BROWSER_JPEG_QUALITY` | no | `55` | JPEG quality |
| `REMOTE_BROWSER_EVERY_NTH_FRAME` | no | `1` | Frame thinning |

#### Rate limits and retries

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `MIN_ACTION_INTERVAL` | no | `2.0` | Pause between actions (sec) |
| `AFTER_APPLY_DELAY` | no | `8.0` | Pause after apply |
| `JITTER` | no | `0.35` | Pause spread |
| `MAX_PER_HOUR` | no | `40` | Applies per hour |
| `MAX_PER_DAY` | no | `180` | Applies per day |
| `LOAD_RETRIES` | no | `3` | Load retries |
| `LOAD_RETRY_DELAY` | no | `2.5` | Delay between load retries |
| `APPLY_RETRIES` | no | `2` | Apply retries |
| `NAVIGATION_TIMEOUT_MS` | no | `45000` | Navigation timeout |
| `CONTENT_TIMEOUT_MS` | no | `20000` | Content timeout |
| `SETTLE_MS` | no | `1200` | DOM settle pause |

#### Owner gate and Admin

| Variable | Required | Safe example shape | Meaning |
|----------|----------|--------------------|---------|
| `ADMIN_USER` | for gate/admin: yes | your login | Shared identity |
| `ADMIN_PASSWORD` | for gate/admin: yes | a strong password | Shared password |
| `ADMIN_SECRET` | in production: yes | `openssl rand -hex 32` or `./scripts/gen_admin_secret.sh` | Signs JWTs (`nexus_token`, `refresh_token`) and admin session |
| `GATE_USER` / `GATE_PASSWORD` | no | (empty) | Gate-only credentials; otherwise `ADMIN_*` are used |
| `AUTH_COOKIE_SECURE` | behind HTTPS: yes | `true` on Fly/Railway | Secure flag on auth cookies |

Behavior:

| Condition | Result |
|-----------|--------|
| `ADMIN_USER` + `ADMIN_PASSWORD` (or `GATE_*`) set | Middleware protects `/` and `/api/*`; public: `/login`, `/logout`, `/api/health`, `/api/auth/refresh`, `/static/*`, `/admin*` |
| Admin pair set | Both gate and `/admin` (`.env` editor) are available |
| Credentials empty | Gate off; `/admin` returns 404 |

#### PDF schedule

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `REPORT_SCHEDULE_ENABLED` | no | `false` | Enable in-process PDF scheduler |
| `REPORT_SCHEDULE_TIMEZONE` | no | `Europe/Minsk` | Timezone |
| `REPORT_SCHEDULE_HOUR` / `MINUTE` | no | `4` / `0` | Run time |
| `REPORT_SCHEDULE_CRON` | no | (empty) | `minute hour * * *` overrides HOUR/MINUTE |
| `REPORT_SCHEDULE_KIND` | no | `work` | Report kind |
| `REPORT_SCHEDULE_PROFILE` | no | `default` | Data profile |

PDFs land in `data/reports/`. Manual: `GET /api/reports/{kind}.pdf`, `POST /api/reports/save`.

#### Parse schedule

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `PARSE_SCHEDULE_ENABLED` | no | `false` | Scheduled parse (keep off locally unless you want it) |
| `PARSE_SCHEDULE_TIMEZONE` | no | `Europe/Minsk` | Timezone |
| `PARSE_SCHEDULE_TIMES` | no | `12:00,00:00` | `HH:MM` list |
| `PARSE_SCHEDULE_PROFILE` | no | `default` | Profile |
| `PARSE_EARLY_STOP_ENABLED` | no | `true` | Early-stop on consecutive fully-duplicate SERP pages (HH + LinkedIn) |
| `PARSE_OLD_STREAK_STOP` | no | `0` | Optional item-level streak (0 = off) |
| `PARSE_MAX_SERP_PAGES` | no | `20` | Max SERP pages per query |
| `PARSE_DUP_PAGE_STOP` | no | `3` | Stop after N fully-duplicate pages |

On tick: HH StartSearch and LinkedIn vacancy collect (when sessions exist), preferably in parallel. Duplicates become `filtered:duplicate`.

#### SMTP alerts

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `ALERT_SMTP_ENABLED` | no | `false` | Master switch |
| `ALERT_SMTP_HOST` | if enabled: yes | (empty) | SMTP host |
| `ALERT_SMTP_PORT` | no | `587` | 587 STARTTLS or 465 SSL |
| `ALERT_SMTP_USER` / `PASSWORD` | as the server requires | (empty) | SMTP login |
| `ALERT_SMTP_FROM` / `TO` | if enabled: `TO` yes | (empty) | From and To |
| `ALERT_SMTP_TLS` | no | `true` | STARTTLS on 587 |
| `ALERT_ON_ERROR` / `CAPTCHA` / `PARSE_FAIL` | no | `true` | Which events to mail |
| `ALERT_RATE_LIMIT_SECONDS` | no | `600` | Anti-flood window for identical mails |

Yandex-shaped example (use an app password; fill values yourself):

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

#### Other

| Variable | Required | Meaning |
|----------|----------|---------|
| `API_KEY` | no | Reserved for later (commented in `.env.example`) |

Do not commit `.env` or a personal `launch.json`.

### 5.4. HH launch criteria (rabota.by / hh.ru)

Primary run artifact: `config/launch.json` or the **Criteria** modal in the UI (strict `key: value` text DSL). JSON shape: `config/launch.example.json`.

Text form in the UI:

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

| Field | Meaning |
|-------|---------|
| `site` | `rabota.by` or `hh.ru` (country must match the catalog) |
| `country` / `city` | Strictly from `config/areas.json` → `area=` |
| `strict` | Drop vacancies from another city |
| `queries` | SERP query strings |
| `remote_or_hybrid` | Require remote or hybrid |
| `skip_gov` | Drop gov markers and `*.gov.*` |
| `python_keywords` | Require a python / developer signal |
| `vacancy_limit` / `apply_limit` | Search and apply caps |
| `dry_run` | Walk the flow without sending a real apply |
| `salary_*` | Legend band $2200-2800; `salary_strict` hard-drops below |
| `level` | Target level for scoring signals |

After UI edits: **Validate** → **Save filters**.

For hh.ru:

```text
site: hh.ru
country: Россия
city: Москва
queries: python developer
…
```

Selection flow:

```
SERP → soft pre-filter (gov)
     → vacancy page
     → evaluate_vacancy (remote, python, location, salary_strict)
     → score → HIGH|MEDIUM|LOW
     → queued | skipped
```

### 5.5. LinkedIn

Workspace switcher in the header: **rabota.by / hh** ↔ **LinkedIn**. There is no official API. Account restriction risk is real: keep `connect_limit` and delays conservative. Details: [docs/linkedin.md](docs/linkedin.md).

| Step | Action |
|------|--------|
| 1 | Switch workspace to LinkedIn |
| 2 | Log in → manual login (window or remote) → **Save session** |
| 3 | Session file: `data/sessions/<profile>.linkedin.storage.json` (does not overwrite HH) |
| 4 | **Criteria** → JSON → `config/linkedin.launch.json` |
| 5 | **Grow network** (limit = `connect_limit`) |
| 6 | **Vacancies** tab → **Collect vacancies** (limit = `vacancy_limit`) |

Key fields from `linkedin.launch.example.json`:

| Key | Default | Meaning |
|-----|---------|---------|
| `locations` | Minsk, Russia, CIS | Location priority |
| `people_queries` | HR, backend developer, … | Networking roles |
| `vacancy_queries` | Python backend, … | Vacancy queries |
| `connect_limit` | 15 | Max Connect actions per run |
| `vacancy_limit` | 40 | Max vacancy links |
| `max_profiles_per_query` | 10 | Profiles from SERP per query×location |
| `min_action_interval` / `after_connect_delay` / `jitter` | 8 / 14 / 0.4 | Pauses |
| `dry_run` | false | Log only, no Connect click |

There is no LinkedIn `CONNECT_LIMIT` in `.env`: edit the file or the **Criteria** modal.

### 5.6. Login modes and remote browser

| Mode | Env | How to use |
|------|-----|------------|
| Local headed Chromium | `HEADLESS=false`, `ENABLE_REMOTE_BROWSER=false` | **Login / Connect** → browser window → sign in by hand → **Session saved** |
| Remote in UI | `HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true` | **Open browser / Login** → screencast modal → mouse and keyboard → **Session saved** |

Sessions:

| Workspace | File |
|-----------|------|
| HH / rabota | `data/sessions/<profile>.storage.json` |
| LinkedIn | `data/sessions/<profile>.linkedin.storage.json` |

One profile may run two independent Chromium instances (`hh` and `linkedin`). Search/apply and LinkedIn grow/collect can run in parallel when slots are free. WebSocket: `/api/remote-browser/ws?profile=&workspace=hh|linkedin`.

### 5.7. UI panels and workflows

Layout:

```
┌─ header: brand · workspace · theme · status ───────┐
│  profile · actions · Criteria · report / parse     │
│  stats                                              │
│  ┌ queue / contacts ┐  ┌ journal ─────────────┐   │
│  │ (+ Explain for HH)│  │ events               │   │
│  └───────────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

| Element | Role |
|---------|------|
| Workspace switch | HH ↔ LinkedIn |
| Profile | Select + create; `●` when a session exists |
| Criteria | Launch modal (HH text DSL or LinkedIn JSON) |
| Theme | system / light / dark (`localStorage` key `aa-theme`) |
| HH stats | HIGH/MEDIUM/LOW, queued, applied, session |
| LinkedIn stats | Contacts / vacancies |
| HH queue | Table (desktop) or cards (&lt;860px); Explain button |
| Journal | Search/apply/linkedin events, refreshed with status |
| Report | PDF schedule hint; save/download menu |
| Remote panel | Screencast status, save/stop |

Safe HH run:

1. Criteria: `dry_run: true`, small `apply_limit` (for example 5).
2. Login → Session = ok.
3. Start search → queue + a couple of Explain views.
4. Adjust launch / `weights.json` if needed.
5. `dry_run: false` → Start apply.

Apply order: among `queued` only, HIGH → MEDIUM → LOW. Captcha / login wall → `waiting_user` and stop; with SMTP enabled, an alert is sent.

### 5.8. Owner gate and Admin

| Component | URL | When available |
|-----------|-----|----------------|
| Owner gate | `/login` | User+password set (`GATE_*` or `ADMIN_*`) |
| Logout | `/logout` | After login |
| Admin env editor | `/admin` → `/admin/env` | `ADMIN_USER` and `ADMIN_PASSWORD` set |
| Health (no auth) | `GET /api/health` | Always public for healthchecks |

Gate cookies: short-lived access JWT `nexus_token` (15 min) and refresh `refresh_token` (14 days). Admin session: signed cookie `aa_admin_session`. Behind HTTPS set `AUTH_COOKIE_SECURE=true`. Secret: `ADMIN_SECRET` (see `./scripts/gen_admin_secret.sh`).

After saving `.env` in `/admin`, **Restart** the process so new variables load.

### 5.9. Remote deploy

Real shipping paths in this repo: **Dockerfile** + **docker-compose** (local), **Railway** (Deploy from Dockerfile, documented), **Fly.io** (`fly.toml`). There is no `railway.toml` or `Procfile`. GitHub Actions does not deploy; it only runs CI.

Principle: one container = Web UI + Playwright jobs + schedulers in one uvicorn. Do not scale multiple replicas against one SQLite file.

#### Railway

Based on [docs/docker-railway.md](docs/docker-railway.md).

1. New Project → Deploy from GitHub (or Docker), root = repo root, builder uses `Dockerfile` (Playwright base + Chromium).
2. Variables (minimum for a protected headless host):

```env
HEADLESS=true
ENABLE_REMOTE_BROWSER=true
ADMIN_USER=your_admin
ADMIN_PASSWORD=strong_password
ADMIN_SECRET=   # output of ./scripts/gen_admin_secret.sh
AUTH_COOKIE_SECURE=true
```

3. Useful schedule variables (after sessions are saved):

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
```

4. Volume on `/app/data` (SQLite, sessions, reports). Without a volume, data disappears on redeploy.
5. Optional Postgres plugin: bind `DATABASE_URL` from Postgres into the web service (`${{Postgres.DATABASE_URL}}` or a copied URL). You still need a volume for sessions/PDFs.
6. Healthcheck: `GET /api/health`.
7. Deploy → public URL → Login via remote screencast → **Save session**.
8. `/admin` to edit `.env` (needs `ADMIN_*`) → Restart.

Railway injects `PORT`; image CMD: `uvicorn … --port ${PORT:-8080}`.

Memory: two Chromium instances per profile roughly doubles usage; keep headroom (often 1-2 GB+), especially with an open screencast.

#### Fly.io

Based on [docs/fly-io.md](docs/fly-io.md) and [`fly.toml`](fly.toml).

```bash
# CLI: https://fly.io/docs/hands-on/install-flyctl/
fly auth login
fly apps create auto-apply-app
fly volumes create auto_apply_app_data --region ams --size 3 --app auto-apply-app
fly secrets set ADMIN_USER='…' ADMIN_PASSWORD='…' ADMIN_SECRET="$(openssl rand -hex 32)" --app auto-apply-app
fly deploy --app auto-apply-app
```

| Fact from `fly.toml` | Value |
|----------------------|-------|
| App name | `auto-apply-app` (if you already have another name, deploy to that app) |
| Region | `ams` |
| Internal port | 8080 |
| Volume | `auto_apply_app_data` → `/app/data` |
| VM | 2 GB RAM, 2 shared CPUs |
| Env in toml | `HEADLESS=true`, `ENABLE_REMOTE_BROWSER=true`, SQLite URL |
| Machines | `min_machines_running = 1`, `auto_stop_machines = off` (keeps schedules alive) |
| Health | `GET /api/health` |

Alternative to manual `fly deploy`: [Fly.io GitHub integration](https://fly.io/docs/launch/continuous-deployment-with-github/). This repo does not use a `FLY_API_TOKEN` secret in GitHub Actions.

The image ships `launch.example.json`; place your `config/launch.json` via volume/SSH or a custom build layer.

### 5.10. API (short)

POST bodies usually include `{"profile":"default"}`. For remote/login confirm add `"workspace": "hh"` or `"linkedin"`.

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/health` | Liveness (public) |
| GET | `/api/config` | Public settings slice |
| GET/POST | `/api/launch*` | Read / validate / save HH launch |
| GET/POST | `/api/profiles*` | List, create, rename, delete |
| POST | `/api/login`, `/api/login/confirm` | HH login and session save |
| POST | `/api/search`, `/api/apply`, `/api/stop` | Search, apply, stop |
| GET | `/api/status`, `/api/stats` | Job status and stats |
| GET | `/api/vacancies`, `/api/vacancies/explain` | Queue and Explain |
| GET | `/api/logs` | Journal (`service=hh\|linkedin`) |
| GET/POST | `/api/remote-browser/*` | Status / start / save / stop |
| WS | `/api/remote-browser/ws` | Frames + input |
| GET/POST | `/api/linkedin/*` | Launch, login, network, vacancies |
| GET/POST | `/api/reports*` | List, save, PDF, generate |
| POST | `/api/auth/refresh` | Refresh access cookie |

### 5.11. Minimal checklist

| # | Check |
|---|--------|
| 1 | `poetry run pytest -q` is green |
| 2 | UI opens; theme switches |
| 3 | Launch **Validate** has no errors |
| 4 | Login → Session = ok |
| 5 | Search with `dry_run: true` and a small limit |
| 6 | Explain shows pros/cons |
| 7 | On PaaS: volume on `/app/data`, remote login, `/api/health` ok |

---

## Poetry and dependencies

Package metadata and CLI: `pyproject.toml` (`poetry run autoapply` → `app.main:run`).  
`requirements.txt` is an export for non-Poetry hosts; version truth is `poetry.lock`.
