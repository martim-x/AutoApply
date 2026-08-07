# Как пользоваться приложением

Пошаговый гайд по Web UI auto-apply-app.

См. также: [getting-started.md](./getting-started.md) · [priorities.md](./priorities.md) · [linkedin.md](./linkedin.md) · [docker-railway.md](./docker-railway.md).

В шапке — переключатель окружения **rabota.by / hh** ↔ **LinkedIn**.  
PDF по расписанию: env `REPORT_SCHEDULE_*` (подсказка в блоке «Отчёт»).  
Парсинг вакансий 2×/день: env `PARSE_SCHEDULE_*` (12:00 и 00:00, timezone; HH + LinkedIn при наличии сессий).

---

## Экран целиком

```
┌─ шапка: бренд · окружение · тема · статус ─────────┐
│  Параметры запуска (launch) + кнопки действий       │
│  статистика HIGH/MEDIUM/LOW / queued / applied      │
│  ┌ очередь вакансий ┐  ┌ журнал ──────────────┐    │
│  │ + Explain         │  │ события поиска/apply │    │
│  └───────────────────┘  └──────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

Высота окна занята целиком: очередь и журнал скроллятся **внутри** панелей.

---

## Тема

Справа/сверху сегмент:

| Иконка | Режим |
|--------|--------|
| монитор | как в системе OS |
| солнце | светлая |
| луна | тёмная |

Выбор пишется в `localStorage` (`aa-theme`).

---

## 1. Профиль

- Селект **Профиль** — изолированные сессии и очереди (`default` и др.).
- Поле + кнопка **+** — создать новый профиль.
- У профиля с сохранённой сессией в списке метка `●`.

---

## 2. Параметры запуска (обязательно перед поиском)

Блок textarea — **строгий формат** `key: value`.

1. Вставьте / отредактируйте текст (см. пример ниже).  
2. **Проверить** — валидация без записи.  
3. **Сохранить фильтры** → `config/launch.json`.

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

Под полем — краткая meta: site · город · area · level · вилка · число queries.

**Частые ошибки валидации**

- `site=rabota.by`, а `country=Россия` → не пройдёт  
- город не из каталога → список допустимых в ошибке  
- `salary_min_usd` > `salary_max_usd` → не пройдёт  

Для hh.ru:

```text
site: hh.ru
country: Россия
city: Москва
queries: python developer
…
```

---

## 3. Логин

### Локально (окно браузера)

1. **Login / Connect**  
2. Войдите на сайт вручную  
3. **Сессия сохранена**  
4. В статистике **Session → ok**

### Remote (встроенный браузер)

Если в `.env` `ENABLE_REMOTE_BROWSER=true`:

1. **Открыть браузер / Login** (или Login remote)  
2. В модалке кликайте и печатайте как в обычном браузере  
3. **Сессия сохранена** внутри модалки  
4. **Закрыть** / **Stop**

Сессия: `data/sessions/<profile>.storage.json`.

---

## 4. Поиск (Start search)

Что происходит:

1. SERP по каждому `query` на выбранном `site` + `area`  
2. Фильтры (gov / remote / python / location / salary_strict)  
3. Scoring → категория и score  
4. Подходящие → `queued`, остальное `skipped`  

Следите за статусом `searching` и журналом слева/справа.

Остановиться: **Stop**.

---

## 5. Очередь и Explain

В таблице (десктоп) или карточках (мобила):

| Поле | Смысл |
|------|--------|
| Cat | HIGH / MEDIUM / LOW |
| Score | 0–100 |
| Filter | `ok` или `filtered:…` |
| Apply | `queued` / `applied` / `skipped` / … |

**Explain** — почему такой score: текст + плюсы/минусы (вклады сигналов).  
Полезно, если странный LOW при «вроде норм» вакансии → правите `weights.json` или launch.

---

## 6. Отклики (Start apply)

Порядок: **HIGH → MEDIUM → LOW** среди `queued`.

- Текст письма: каталог `letters/` (`LETTER_PATH`, стиль через `LETTER_STYLE`)  
- Лимиты: `MAX_PER_HOUR` / `MAX_PER_DAY` + паузы из `.env`  
- `dry_run: true` в launch — пройти сценарий **без** реальной отправки  

Статус `applying` → в конце `done` / `error`.

---

## 7. Журнал

Фиксированная панель с подсветкой:

- `filtered:…` — отсев  
- `HIGH|MEDIUM|LOW` / score  
- `applied` / `queued` / ошибки  

Обновление ~раз в 2 секунды вместе со статусом.

---

## 8. Рекомендуемый безопасный прогон

1. `dry_run: true`, `apply_limit: 5`  
2. Search → глянуть очередь и пару Explain  
3. При необходимости поправить launch / weights  
4. `dry_run: false` → Apply  

---

## Кнопки (шпаргалка)

| Кнопка | Действие |
|--------|----------|
| Проверить | валидация launch-текста |
| Сохранить фильтры | запись `launch.json` |
| Login / Connect | локальный логин |
| Открыть браузер | remote screencast |
| Сессия сохранена | записать cookies |
| Start search | поиск + скоринг |
| Start apply | отклики по очереди |
| Stop | стоп job / remote |
| Explain | разбор весов вакансии |

---

## API (если дергаете руками)

Базовый профиль в теле: `{"profile":"default"}`.

| Method | Path |
|--------|------|
| POST | `/api/login`, `/api/login/confirm` |
| POST | `/api/search`, `/api/apply`, `/api/stop` |
| GET | `/api/status`, `/api/vacancies`, `/api/logs` |
| GET | `/api/vacancies/explain?vacancy_id=` |
| GET/POST | `/api/launch`, `/api/launch/validate`, `/api/launch/text` |

Полный список — в корневом [README](../README.md#api).
