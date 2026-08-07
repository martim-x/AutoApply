# Технические решения

Зафиксированные решения auto-apply-app: зачем так сделано и где смотреть код.

См. также: [getting-started.md](./getting-started.md) · [user-guide.md](./user-guide.md) · [priorities.md](./priorities.md).

---

## 1. Продуктовый контур

**Решение:** один процесс FastAPI = Web UI + REST API + фоновый Playwright-воркер + SQLite.

**Почему:** личный инструмент, не микросервисная платформа. Меньше деплоя, проще статус `idle / searching / applying` в одном месте.

**Альтернатива (не выбрана):** отдельный worker + Redis queue — избыточно для одного пользователя.

---

## 2. Браузерная сессия вместо HH OAuth API

**Решение:** ручной логин → Playwright `storage_state` (cookies) на диск.

**Почему:** для BY (`+375`) OAuth HH давал `geo_forbidden` даже через rabota.by / Android `client_id`. Браузерный путь работает на том же UI, что видит кандидат.

**Цена:** хрупкость DOM/селекторов, нужен Chromium, captcha/2FA — руками.

**Код:** `app/infrastructure/browser/gateway.py`, `launch.py`, сессии в `data/sessions/`.

---

## 3. Слои DDD (монолит)

```
interfaces  →  application  →  domain
                  ↑
            infrastructure
```

| Слой | Ответственность | Примеры |
|------|-----------------|---------|
| **domain** | правила без FastAPI/Playwright | фильтры, scoring, `LaunchProfile`, ports |
| **application** | use-cases | `AppService`: login/search/apply/explain/launch |
| **infrastructure** | адаптеры | SQLite UoW, Playwright gateway, remote CDP, settings |
| **interfaces** | HTTP / WS / HTML | `routes.py`, templates, static |

**Почему:** смена БД или браузерного драйвера не должна ломать scoring и фильтры. Порты: `app/domain/ports.py`.

---

## 4. Launch-профиль как единый источник прогона

**Решение:** `config/launch.json` (+ строгий text DSL в UI) перекрывает `.env` для site / area / queries / фильтров / вилки / level.

**Почему:** один артефакт «как ищу сегодня», валидируемый (`site`↔`country`, город из каталога).

**Парсинг:** `app/domain/launch_profile.py`  
**Каталог area:** `config/areas.json`  
**API:** `/api/launch`, `/api/launch/validate`, `/api/launch/text`, `/api/launch/json`

---

## 5. Двухступенчатый отбор вакансий

```
SERP → мягкий pre-filter (gov)
     → открытие карточки
     → жёсткий evaluate_vacancy (remote, python, location, salary_strict)
     → score_vacancy / categorize → HIGH|MEDIUM|LOW
     → queued | skipped
```

**Фильтры** (`app/domain/filters.py`) — бинарный pass/fail.  
**Scoring** (`app/domain/scoring/`) — непрерывный fit + Explain.

**Почему не всё в одном score:** «офис-only» и gov должны отсекаться, а не просто получать LOW и засорять очередь.

---

## 6. Weight-graph scoring

**Решение:** декларативный JSON `config/weights.json`: сигнал → `weight` ∈ [−1, +1] + regex → сумма → нормализация 0..100 → пороги HIGH/MEDIUM/LOW.

**Динамические сигналы из launch** (не в JSON): локация, вилка ЗП, level.

**Почему JSON:** править приоритеты без деплоя кода; Explain строится из тех же contributions.

**Источник правды по смыслу весов:** Obsidian `07 Legend` → см. [priorities.md](./priorities.md).

**Explain:** `GET /api/vacancies/explain` + кнопка в UI.

---

## 7. Remote browser (CDP screencast)

**Решение:** серверный Chromium + `Page.startScreencast` → JPEG по WebSocket; мышь/клавиатура → Playwright.

**Почему:** на Railway/Docker нет нормального GUI; noVNC/Xvfb тяжелее для MVP.

**Латентность:** обычно 0.2–2 с — ок для логина, не для скоростного серфинга.

**Код:** `app/infrastructure/browser/remote_session.py`, WS `/api/remote-browser/ws`.

---

## 8. Хранение данных

**Решение сейчас:** SQLite (`DATABASE_URL=sqlite:///./data/auto_apply_app.sqlite`).

**Postgres:** тот же UnitOfWork; `DATABASE_URL=postgresql://…` (Railway)
или `postgresql+psycopg://…` → `PostgresUnitOfWork` (sync SQLAlchemy engine + psycopg3).

**Почему SQLite:** zero-ops локально, файл в `./data`, удобно бэкапить вместе с сессиями.

### 8.1 Durability прогона

Каждая запись в UoW коммитится отдельно (не одна транзакция на весь Search/Apply).  
Падение mid-run → статус `error` / journal `job_aborted`, уже сохранённые вакансии/отклики остаются.  
Ошибка одного query → `unit_failed`, остальные queries продолжают.  
Checkpoint: `last_query` / `processed_count` в `job_state.stats_json`.

Подробнее: [alerts.md](./alerts.md).

---

## 8.2 SMTP-алерты

Опциональные письма при captcha / error / parse-fail (`ALERT_SMTP_*`).  
Sync `smtplib`, короткий timeout — один процесс на Railway.  
Captcha → алерт + `waiting_user` + stop (без флуда: rate-limit).

Код: `app/infrastructure/alerts/`, `app/application/alerts.py`.

---

## 9. Rate limits и «human-like»

**Решение:** интервалы + jitter + `MAX_PER_HOUR` / `MAX_PER_DAY` + retry загрузок/откликов.

**Почему:** снизить бан/капчу; не гонка по DOM.

Настройки в `.env`: `MIN_ACTION_INTERVAL`, `AFTER_APPLY_DELAY`, `JITTER`, …

---

## 10. UI

**Решение:** серверные Jinja-шаблоны + vanilla JS/CSS (без React).

| Фича | Решение |
|------|---------|
| Темы | system / light / dark, `localStorage` + `prefers-color-scheme` |
| Высота | app-shell на `100dvh`: контролы ограничены, очередь+журнал flex-fill |
| Mobile | карточки &lt;860px, таблица на десктопе; touch ≥44px |
| Иконки | SVG sprite + `<use href="#i-…">` |

**Почему без SPA:** один бинарник деплоя, мало зависимостей фронта.

---

## 11. Poetry как источник зависимостей

**Решение:** `pyproject.toml` + `poetry.lock`; `requirements.txt` — экспорт для Docker/pip.

**CLI:** `poetry run autoapply` → `app.main:run`.

---

## 12. Сознательные отказы

| Не делаем | Почему |
|-----------|--------|
| HH OAuth tokens | geo_forbidden для BY |
| Автозаполнение пароля | безопасность + 2FA |
| LLM-ранжирование в MVP | прозрачность весов важнее |
| Force-apply на LOW без фильтра | очередь должна быть осмысленной |
| Коммит `.env` / `launch.json` | секреты и личные фильтры |

---

## Карта каталогов

```
app/
  domain/           # entities, filters, scoring/, launch_profile, ports
  application/      # AppService, letter, rate limits
  infrastructure/
    settings.py
    db/sqlite/      # UoW
    browser/        # gateway, job_runner, remote_session, launch
  interfaces/
    api/routes.py
    web/            # templates + static
config/
  weights.json      # дерево весов
  areas.json        # страны/города → area_id
  launch.example.json
docs/               # эта документация
tests/
letter_universal.txt
```

---

## Статусы job

`idle` → `logging_in` / `waiting_user` → `searching` → `applying` → `done` | `error`  
`Stop` прерывает текущий job (и remote browser при необходимости).
