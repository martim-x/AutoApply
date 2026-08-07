# Приоритеты: Legend → дерево весов

Источник профиля кандидата: Obsidian  
`/Users/timofejmarusko/Documents/VisualStudioCodeRepos/Obsidian/07 Legend`

В auto-apply-app это зафиксировано в трёх местах:

| Слой | Файл / механизм | Что кодирует |
|------|-----------------|--------------|
| Жёсткие фильтры | launch + `filters.py` | must-have / must-not |
| Launch defaults | `config/launch.example.json` | вилка, level, site, city |
| Weight graph | `config/weights.json` + динамика launch | HIGH / MEDIUM / LOW |

---

## Канон из Legend (сжато)

| Поле | Значение |
|------|----------|
| Роль | Middle+ Python → рост к Senior |
| Опыт | ~4.5–5 лет: NEMIKA (Django WMS) + WhiteSnake (FastAPI / K8s) |
| Вилка | **$2200–2800** |
| Формат | remote или hybrid (офис-only — отсев / сильный минус) |
| Стек-плюс | Python, FastAPI, Django/DRF, PostgreSQL, Redis, Celery/Rabbit/Kafka, Docker/K8s, pytest, observability |
| Команда | продуктовая / осмысленный ownership, не «любой аутсорс любой ценой» |
| Минусы | gov, PHP/1C как основной стек, чистый QA, junior-only при цели middle+ |

Английский B2 в Legend есть как факт профиля; в scoring MVP отдельно не выделен (можно добавить сигнал в `weights.json`).

---

## Как это бьётся на поведение бота

### 1) Must-have (фильтр = не попадёт в очередь)

- remote **или** hybrid (`remote_or_hybrid: true`)
- не gov (`skip_gov: true`)
- python/разработчик-сигнал (`python_keywords: true`)
- при `strict: true` — другой город → `filtered:location`
- при `salary_strict: true` — ЗП явно ниже вилки → `filtered:salary`

### 2) Soft fit (score, не бинарный отсев)

Плюсы (примеры из `weights.json`):

- Python-роль в заголовке  
- FastAPI / Django  
- Postgres, очереди, Redis, Docker/K8s  
- remote / hybrid  
- упоминание зарплаты / пересечение с вилкой launch  
- level middle+  

Минусы:

- office-only  
- gov-маркеры  
- чужой стек (PHP, 1C, …)  
- junior при цели middle+  
- ЗП ниже вилки (`salary_below`)  
- другой город (`location_other_city`)  

Агрегация → score 0..100 → пороги `thresholds.high` / `thresholds.medium` → категория.

### 3) Порядок откликов

Только среди прошедших фильтр: **HIGH → MEDIUM → LOW**.

LOW в очереди возможен (мало плюсов, но фильтр пройден). Смотрите Explain перед массовым Apply.

---

## Где править приоритеты

### Быстрый тюнинг «сегодняшнего» поиска

`config/launch.json` / UI «Параметры запуска»:

- город / site  
- queries  
- вилка и `salary_strict`  
- `level`  
- `apply_limit`, `dry_run`  

### Долгосрочный тюнинг «что считаем хорошей вакансией»

`config/weights.json`:

1. Меняете `weight` сигнала (−1…+1)  
2. При необходимости — regex `patterns`  
3. Пороги `thresholds`  
4. Перезапуск uvicorn  

Проверка: Search → Explain на 2–3 знакомых вакансиях.

### Каталог городов

`config/areas.json` — если нужен новый город/area_id HH.

---

## Сопроводительное письмо

`letter_universal.txt` — универсальный текст отклика.  
В Legend есть варианты писем (`Сопроводительные_письма.md`); в бот сейчас один файл — правьте его под актуальный тон.

---

## Чеклист согласованности с Legend

- [ ] Launch: `level: middle+`, вилка 2200–2800  
- [ ] `remote_or_hybrid: true`, `skip_gov: true`  
- [ ] Queries про Python developer / разработчик  
- [ ] В `weights.json` FastAPI/Django/очереди весят заметно больше «просто python»  
- [ ] Office-only и gov дают сильный минус / фильтр  
- [ ] Письмо не противоречит самопрезентации Legend  

Если Legend обновился — сначала этот чеклист, потом правки JSON/launch.
