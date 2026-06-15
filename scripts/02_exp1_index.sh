#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ЭКСПЕРИМЕНТ 1 — ОТСУТСТВУЮЩИЙ ИНДЕКС  (таблица orders, колонка customer_id)
# Цикл: baseline → нагрузка по неиндексированной колонке → детект →
#       применение CREATE INDEX → верификация исчезновения рекомендации.
# Результаты пишутся в out/exp1_*.txt
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
source ./00_env.sh

T="orders"
COL="customer_id"
EXP="exp1"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║ ЭКСПЕРИМЕНТ 1: отсутствующий индекс на ${T}.${COL}         "
echo "╚══════════════════════════════════════════════════════════╝"

echo "[0] Сбрасываю статистику запросов и таблиц..."
pg -c "SELECT pg_stat_statements_reset();" >/dev/null 2>&1 || \
  echo "  (pg_stat_statements_reset недоступен — продолжаю)"
pg -c "SELECT pg_stat_reset();" >/dev/null
pg -c "DROP INDEX IF EXISTS idx_orders_customer_id;" >/dev/null
# ВАЖНО: pg_stat_reset() обнуляет n_live_tup. Без ANALYZE условие сервиса
# n_live_tup > MIN_TABLE_ROWS не выполнится и рекомендация не появится.
echo "    Прогоняю ANALYZE, чтобы вернуть n_live_tup (иначе сервис не увидит таблицу)."
pg -c "ANALYZE ${T};" >/dev/null

echo "[1] Проверяю, что таблица на месте и без индекса на ${COL}:"
pg -c "SELECT count(*) AS orders_rows FROM ${T};"
pg -c "SELECT indexname FROM pg_indexes WHERE tablename='${T}';"

echo "    EXPLAIN ANALYZE одного запроса ДО индекса:"
pg -c "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM ${T} WHERE ${COL} = 12345;" \
  | tee "$OUT_DIR/${EXP}_explain_before.txt"

echo "[2] СОСТОЯНИЕ 'ДО': запускаю нагрузку (5 мин, 4 потока)..."
./gen_load.sh 300 4

echo "[3] Метрики ДО (out/${EXP}_before.txt):"
pg -c "
SELECT relname, seq_scan, idx_scan, seq_tup_read, n_live_tup,
       pg_size_pretty(pg_relation_size(relid)) AS size
FROM pg_stat_user_tables WHERE relname = '${T}';
" | tee "$OUT_DIR/${EXP}_before.txt"

pg -c "
SELECT calls, round(mean_exec_time::numeric,2) AS mean_ms,
       round(total_exec_time::numeric,2) AS total_ms
FROM pg_stat_statements
WHERE query ILIKE '%${T}%${COL}%' AND query NOT ILIKE '%pg_stat%'
ORDER BY total_exec_time DESC LIMIT 3;
" | tee -a "$OUT_DIR/${EXP}_before.txt" || true

echo "[4] ДЕТЕКТ: обновляю статистику и запускаю цикл анализа..."
echo "    (ANALYZE обязателен: pg_stat_reset обнулил n_live_tup, а условие"
echo "     MISSING_INDEXES требует n_live_tup > MIN_TABLE_ROWS — без ANALYZE будет 0)"
pg -c "ANALYZE ${T};" >/dev/null
wait_cycle
if has_rec "Missing index" && has_rec "$T"; then
  echo "  ✓ Сервис ВЫДАЛ рекомендацию по отсутствующему индексу на '${T}'."
else
  echo "  ⚠ Рекомендация не появилась. Проверь пороги MIN_SEQ_SCANS/SEQ_SCAN_PCT_WARN."
  echo "    Текущие рекомендации:"
  fetch_recs
fi
echo "  >>> СЕЙЧАС сделай СКРИНШОТ интерфейса $ADVISOR_URL (рекомендация index)."
echo "  >>> (seq_scan берётся из psql-вывода выше — отдельной панели в Grafana нет)"
read -rp "  Нажми Enter, когда скриншот 'ДО' сделан..."

echo "[5] ПРИМЕНЕНИЕ рекомендации (та же команда, что выдал сервис):"
echo "    CREATE INDEX CONCURRENTLY idx_orders_customer_id ON ${T} (${COL});"
pg -c "CREATE INDEX CONCURRENTLY idx_orders_customer_id ON ${T} (${COL});"

echo "[6] СОСТОЯНИЕ 'ПОСЛЕ': повторяю нагрузку (2 мин)..."
pg -c "SELECT pg_stat_reset();" >/dev/null
pg -c "ANALYZE ${T};" >/dev/null
./gen_load.sh 120 4

echo "    EXPLAIN ANALYZE того же запроса ПОСЛЕ индекса:"
pg -c "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM ${T} WHERE ${COL} = 12345;" \
  | tee "$OUT_DIR/${EXP}_explain_after.txt"

echo "[7] Метрики ПОСЛЕ (out/${EXP}_after.txt):"
pg -c "
SELECT relname, seq_scan, idx_scan, seq_tup_read, n_live_tup,
       pg_size_pretty(pg_relation_size(relid)) AS size
FROM pg_stat_user_tables WHERE relname = '${T}';
" | tee "$OUT_DIR/${EXP}_after.txt"

pg -c "
SELECT calls, round(mean_exec_time::numeric,2) AS mean_ms,
       round(total_exec_time::numeric,2) AS total_ms
FROM pg_stat_statements
WHERE query ILIKE '%${T}%${COL}%' AND query NOT ILIKE '%pg_stat%'
ORDER BY total_exec_time DESC LIMIT 3;
" | tee -a "$OUT_DIR/${EXP}_after.txt" || true

echo "[8] ВЕРИФИКАЦИЯ: обновляю статистику и запускаю цикл анализа..."
pg -c "ANALYZE ${T};" >/dev/null
wait_cycle
if has_rec "Missing index" && has_rec "$T"; then
  echo "  ⚠ Рекомендация всё ещё присутствует (проверь, что нагрузка после шла по индексу)."
else
  echo "  ✓ Рекомендация по '${T}' ИСЧЕЗЛА. Цикл замкнут."
fi
echo "  >>> Сделай СКРИНШОТ интерфейса без рекомендации (состояние 'ПОСЛЕ')."
echo ""
echo "ИТОГ Эксп.1: сравни out/${EXP}_before.txt и out/${EXP}_after.txt — mean_ms и seq_scan/idx_scan."
