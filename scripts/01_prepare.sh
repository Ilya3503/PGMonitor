#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ПОДГОТОВКА. Один раз перед всеми экспериментами.
# Создаёт таблицу events (~5 млн строк) без индекса на user_id.
# Идемпотентно: если таблица уже есть с нужным числом строк — пропускает.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
source ./00_env.sh

ROWS_TARGET=5000000

echo "== Подготовка таблицы events =="

EXISTS=$(pg_scalar "SELECT to_regclass('public.events') IS NOT NULL;")
if [ "$EXISTS" = "t" ]; then
  CNT=$(pg_scalar "SELECT count(*) FROM events;")
  echo "Таблица events уже существует, строк: $CNT"
  if [ "$CNT" -ge "$ROWS_TARGET" ]; then
    echo "Достаточно строк, пропускаю генерацию."
    exit 0
  fi
  echo "Строк меньше цели, пересоздаю."
fi

pg <<SQL
DROP TABLE IF EXISTS events;

CREATE TABLE events (
    id          bigserial PRIMARY KEY,
    user_id     integer       NOT NULL,
    event_type  text          NOT NULL,
    payload     text,
    created_at  timestamptz   NOT NULL DEFAULT now()
);

-- 5 млн строк. user_id в диапазоне 1..100000 — селективная колонка,
-- идеально показывает разницу Seq Scan vs Index Scan.
INSERT INTO events (user_id, event_type, payload, created_at)
SELECT
    (random() * 100000)::int + 1,
    (ARRAY['login','logout','click','view','purchase'])[(random()*4)::int + 1],
    repeat('x', 50),
    now() - (random() * interval '365 days')
FROM generate_series(1, ${ROWS_TARGET});

-- ВАЖНО: индекс на user_id НЕ создаём — это и есть проблема для Эксп.1.
ANALYZE events;
SQL

echo "Готово. Итоговое число строк:"
pg -c "SELECT count(*) AS events_rows FROM events;"
echo "Размер таблицы:"
pg -c "SELECT pg_size_pretty(pg_total_relation_size('events')) AS total_size;"
