# Чеклист прогона экспериментов (цель — уложиться в ~2 часа)

Скрипты лежат в `scripts/`, результаты пишутся в `out/`. Перед стартом — `chmod +x scripts/*.sh`.

## Шаг 0. Поднять стенд и проверить (10 мин)

1. `docker compose up -d`
2. `docker compose ps` — все сервисы `healthy`.
3. Открой и проверь, что отвечают: Grafana `:3000`, pg-advisor `:9188`, pgAdmin `:5050`.
4. **Сверь числа** (подробности — в `CONFIG_PATCHES.md`, сделай ДО первого запуска):
   - docker-compose, pg-advisor: `TOTAL_RAM_MB: 6144` (НЕ 1024).
   - postgresql.conf: `shared_buffers = 1536MB`, `effective_cache_size = 4608MB`.
   - `ANALYSIS_INTERVAL_SEC: 60` (или пусть скрипты дёргают /recompute — он синхронный).
   Если правил — `docker compose up -d` заново. Сверка:
   `docker exec -it postgres psql -U admin -d dvdrental -c "SHOW shared_buffers;"`
5. Проверь, что `pg_stat_statements` активно:
   `docker exec -it postgres psql -U admin -d dvdrental -c "SELECT count(*) FROM pg_stat_statements;"`
   Если ошибка — добавь в shared_preload_libraries и `CREATE EXTENSION pg_stat_statements;`, рестарт.
6. Правь `scripts/00_env.sh`, если имя контейнера/пользователь/порт отличаются.

## Шаг 1. Проверка данных (2 мин — данные создаёт init-скрипт сам)

Таблицы (`orders`, `order_items` и др.) создаёт init `02-large-data.sql` при ПЕРВОМ
старте контейнера (когда `./data` пустая). Отдельный скрипт подготовки НЕ нужен.
Проверь, что данные на месте и индекса на customer_id нет:
```
docker exec -it postgres psql -U admin -d dvdrental -c "SELECT count(*) FROM orders;"
docker exec -it postgres psql -U admin -d dvdrental -c "SELECT indexname FROM pg_indexes WHERE tablename='orders';"
```
Если таблиц нет (стенд уже запускался на непустой ./data) — чистый старт:
`docker compose down -v`, удали папку `./data`, затем `docker compose up -d`.

## Шаг 2. Эксперимент 1 — индекс (~12 мин)

```
./scripts/02_exp1_index.sh
```
- 5 мин нагрузка «до» (orders.customer_id) → детект → **скриншот рекомендации** (по запросу скрипта, Enter) →
  CREATE INDEX → 2 мин нагрузка «после» → верификация → **скриншот без рекомендации**.
- Не забудь снять **дашборд Grafana** на пике seq_scan (во время нагрузки «до»).
- Результаты: `out/exp1_before.txt`, `out/exp1_after.txt`, `out/exp1_explain_before.txt`, `out/exp1_explain_after.txt`.

## Шаг 3. Эксперимент 2 — bloat (~8 мин)

```
./scripts/03_exp2_bloat.sh
```
- Отключает автовакуум → 10× UPDATE → детект → **скриншот** → VACUUM → верификация → **скриншот**.
- Результаты: `out/exp2_before.txt`, `out/exp2_after.txt`.

## Шаг 4. Эксперимент 3 — конфигурация (~20 мин, два рестарта)

Фаза «до»:
1. В `configs/postgres/postgresql.conf` выстави `shared_buffers = 128MB`.
2. `docker compose up -d postgres` (рестарт), дождись healthy.
3. `./scripts/04_exp3_config.sh before` → **скриншот рекомендации config** + **дашборд Cache hit ratio**.

Фаза «после»:
4. Верни `shared_buffers = 1536MB` (норма = 25% от 6144).
5. `docker compose up -d postgres`, дождись healthy.
6. `./scripts/04_exp3_config.sh after` → **скриншот без рекомендации**.
- Результаты: `out/exp3_before.txt`, `out/exp3_after.txt`.

## Шаг 5. Сбор чисел в шаблон (30 мин)

Открой `section6_template.md`. По каждому эксперименту перенеси из `out/*.txt`:
- Эксп.1: mean_ms до/после, seq_scan/idx_scan, тип скана из EXPLAIN (Seq Scan → Index Scan).
- Эксп.2: dead_pct до/после, heap_size до/после.
- Эксп.3: cache_hit_pct до/после.
Заполни сводную таблицу 6.6. Вставь скриншоты на места `[СКРИНШОТ ...]`.

## Скриншоты — полный список (не потеряй ни один)

- Архитектурная схема стенда (у тебя есть).
- Эксп.1: рекомендация index в интерфейсе; интерфейс без неё; дашборд Grafana (seq_scan/время).
- Эксп.2: рекомендация bloat; интерфейс без неё.
- Эксп.3: рекомендация shared_buffers; интерфейс без неё; (опц.) дашборд cache hit.
- Общий вид HTML-интерфейса со списком рекомендаций (для раздела 5, описание интерфейса).

## Если что-то не сработало

- Рекомендация не появилась → пороги в `config.py` строже, чем твой эффект. Снизь
  `MIN_SEQ_SCANS`/`BLOAT_RATIO_WARN` через environment и повтори цикл (`curl -X POST :9188/recompute`).
- `/recompute` не отвечает → скрипт сам подождёт полный цикл; либо проверь эндпоинт.
- Долго ждать цикл → на время прогона можно выставить `ANALYSIS_INTERVAL_SEC: 30`.
