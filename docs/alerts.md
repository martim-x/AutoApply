# SMTP-алерты и устойчивость прогона

Кратко: как включить почтовые уведомления и почему частичный прогресс не теряется при сбое.

См. также: [architecture.md](./architecture.md) · [getting-started.md](./getting-started.md).

---

## 1. Настройка SMTP

В `.env` (секреты не коммитить):

```env
ALERT_SMTP_ENABLED=true
ALERT_SMTP_HOST=smtp.example.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USER=bot@example.com
ALERT_SMTP_PASSWORD=...
ALERT_SMTP_FROM=bot@example.com
ALERT_SMTP_TO=you@example.com
ALERT_SMTP_TLS=true
ALERT_ON_ERROR=true
ALERT_ON_CAPTCHA=true
ALERT_ON_PARSE_FAIL=true
ALERT_RATE_LIMIT_SECONDS=600
```

| Переменная | Смысл |
|------------|--------|
| `ALERT_SMTP_ENABLED` | мастер-выключатель (по умолчанию `false`) |
| `ALERT_SMTP_HOST` / `PORT` | SMTP-сервер |
| `ALERT_SMTP_USER` / `PASSWORD` | логин (если сервер требует) |
| `ALERT_SMTP_FROM` / `TO` | отправитель и ваш ящик |
| `ALERT_SMTP_TLS` | `STARTTLS` (обычно `true` на 587; на 465 код использует SSL) |
| `ALERT_ON_*` | какие события слать |
| `ALERT_RATE_LIMIT_SECONDS` | антифлуд: одно и то же письмо не чаще окна (по умолчанию 10 мин) |

### Yandex Mail (пример)

В `.env.example` уже указан пример `ALERT_SMTP_TO=you@example.com`. Остальное задаёте сами:

```env
ALERT_SMTP_ENABLED=true
ALERT_SMTP_HOST=smtp.yandex.ru
ALERT_SMTP_PORT=465
ALERT_SMTP_USER=you@example.com
ALERT_SMTP_PASSWORD=app-password
ALERT_SMTP_FROM=you@example.com
ALERT_SMTP_TO=you@example.com
ALERT_SMTP_TLS=true
```

- **465** — implicit SSL (`SMTP_SSL`)
- **587** — STARTTLS (`ALERT_SMTP_TLS=true`)

Нужен пароль приложения Яндекса (не обычный пароль от ящика), если включена 2FA.

Если `ENABLED=true`, но нет `HOST` или `TO`, в UI появятся soft-default уведомления, письма не уйдут.

Код: `app/infrastructure/alerts/smtp.py`, `app/application/alerts.py`, настройки в `Settings`.

---

## 2. Что вызывает алерт

| Событие | Условие | Поведение job |
|---------|---------|----------------|
| **captcha** / LinkedIn checkpoint | `ALERT_ON_CAPTCHA` | `waiting_user`, прогон **останавливается** |
| **need_manual** / login wall | `ALERT_ON_CAPTCHA` | `waiting_user`, стоп |
| **error** / `job_aborted` / browser crash | `ALERT_ON_ERROR` | статус `error`, данные уже сохранённые остаются |
| **serp_fail** / `unit_failed` / parse schedule error | `ALERT_ON_PARSE_FAIL` | юнит пропускается, остальные queries продолжают (если безопасно) |

На captcha письма не «долбят»: rate-limit + немедленный stop/`waiting_user`.

В UI: строка «Последний алерт» + поле `last_alert` в `/api/status`.

---

## 3. Модель durability (ACID-ish amortized)

Один Railway-процесс, SQLite. Каждый вызов репозитория открывает своё соединение и **коммитит** (`SqliteUnitOfWork._conn`).

Практический смысл:

1. После каждой вакансии (upsert / apply attempt / LinkedIn contact) прогресс уже на диске.
2. Падение посередине прогона → job → `error` / `job_aborted`, **очередь и отклики не откатываются**.
3. Один query/SERP упал → journal `unit_failed`, следующие queries продолжаются.
4. Captcha → vacancy остаётся `queued`, остальной apply не продолжается.
5. Checkpoint в `job_state.stats_json`: `last_query`, `processed_count` (без миграции схемы).

Journal:

- `unit_failed` — упал один элемент, прогон жив  
- `job_aborted` — фатальный exception всего job (после `safe_run`)

Идемпотентность: дубликаты уже фильтруются (`filtered:duplicate`).

---

## 4. Расписания и PDF-отчёт на почту

Тот же канал `ALERT_SMTP_*` используется и для **scheduled PDF-отчётов**:

- после `generate_scheduled_report` → HTML-тело (статистика) + PDF-вложение;
- сбой SMTP **не валит** scheduler: journal `report_email_error` / `report_email_skipped`, PDF остаётся в `data/reports/`;
- вручную: `POST /api/reports/save` с `"email": true`.

Слоты (не зависят от SMTP):

- парсинг: `PARSE_SCHEDULE_ENABLED` + `PARSE_SCHEDULE_TIMES` (по умолчанию `12:00,00:00`) + timezone;
- PDF: `REPORT_SCHEDULE_ENABLED` + `REPORT_SCHEDULE_HOUR/MINUTE` (по умолчанию 04:00) или `REPORT_SCHEDULE_CRON`.

Smoke без ожидания полуночи: один ближайший `HH:MM` в `PARSE_SCHEDULE_TIMES` и соседний час/минута для report — см. [getting-started.md](./getting-started.md).

При ошибке scheduled parse дополнительно уходит алерт `parse_schedule_error` (если включены error/parse-fail флаги).

После успешного parse-cron (если в `launch.json` → `schedule.email_report_after_run: true`) отправляется тот же HTML+PDF отчёт, что и у `REPORT_SCHEDULE_*` (канал `ALERT_SMTP_*`).
