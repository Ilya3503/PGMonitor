#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ЭКСПЕРИМЕНТ 1 — ОТСУТСТВУЮЩИЙ ИНДЕКС
# Цикл: baseline → нагрузка по неиндексированной колонке → детект →
#       применение CREATE INDEX → верификация исчезновения рекомендации.
# Все метрики до/после пишутся в out/exp1_*.txt
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
source ./00_env.sh

T="events"
EXP="exp1"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║ ЭКСПЕРИМЕНТ 1: отсутствующий индекс на ${T}.user_id        "
echo "╚══════════════════════════════════════════════════════════╝"

# 0. Сброс статистики, чтобы счётчики seq_scan были чистыми для этого опыта
echo "[0] Сбрасываю статистику запросов и таблиц..."
pg -c "SELECT pg_stat_statements_reset();" >/dev/null 2>&1 || \
  echo "  (pg_stat_statements_reset недоступен — продолжаю)"
pg -c "SELECT pg_stat_reset();" >/dev/null

# Убедимся, что индекса нет
pg -c "DROP INDEX IF EXISTS idx_events_user_id;" >/dev/null

echo "[1] СОСТОЯНИЕ 'ДО': запускаю нагрузку (5 мин, 4 потока)..."
echo "    EXPLAIN ANALYZE одного запроса ДО индекса:"
pg -c "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM events WHERE user_id = 42;" \
  | tee "$OUT_DIR/${EXP}_explain_before.txt"

./gen_load.sh 300 4

echo "[2] Метрики ДО (сохраняю в out/${EXP}_before.txt):"
pg -c "
SELECT relname, seq_scan, idx_scan, seq_tup_read, n_live_tup,
       pg_size_pretty(pg_relation_size(relid)) AS size
FROM pg_stat_user_tables WHERE relname = '${T}';
" | tee "$OUT_DIR/${EXP}_before.txt"

pg -c "
SELECT calls, round(mean_exec_time::numeric,2) AS mean_ms,
       round(total_exec_time::numeric,2) AS total_ms
FROM pg_stat_statements
WHERE query ILIKE '%events%user_id%' AND query NOT ILIKE '%pg_stat%'
ORDER BY total_exec_time DESC LIMIT 3;
" | tee -a "$OUT_DIR/${EXP}_before.txt" || true

echo "[3] ДЕТЕКТ: запускаю цикл анализа и проверяю рекомендацию..."
wait_cycle
if has_rec "Missing index" && has_rec "$T"; then
  echo "  ✓ Сервис ВЫДАЛ рекомендацию по отсутствующему индексу на '${T}'."
else
  echo "  ⚠ Рекомендация пока не появилась. Проверь порог MIN_SEQ_SCANS/SEQ_SCAN_PCT_WARN"
  echo "    или повтори нагрузку. Текущие рекомендации:"
  fetch_recs
fi
echo "  >>> СЕЙЧАС сделай СКРИНШОТ интерфейса $ADVISOR_URL (рекомендация index/critical)."
read -rp "  Нажми Enter, когда скриншот 'ДО' сделан..."

echo "[4] ПРИМЕНЕНИЕ рекомендации (та же команда, что выдал сервис):"
echo "    CREATE INDEX CONCURRENTLY idx_events_user_id ON events (user_id);"
pg -c "CREATE INDEX CONCURRENTLY idx_events_user_id ON events (user_id);"

echo "[5] СОСТОЯНИЕ 'ПОСЛЕ': повторяю нагрузку (2 мин)..."
pg -c "SELECT pg_stat_reset();" >/dev/null
./gen_load.sh 120 4

echo "    EXPLAIN ANALYZE того же запроса ПОСЛЕ индекса:"
pg -c "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM events WHERE user_id = 42;" \
  | tee "$OUT_DIR/${EXP}_explain_after.txt"

echo "[6] Метрики ПОСЛЕ (сохраняю в out/${EXP}_after.txt):"
pg -c "
SELECT relname, seq_scan, idx_scan, seq_tup_read, n_live_tup,
       pg_size_pretty(pg_relation_size(relid)) AS size
FROM pg_stat_user_tables WHERE relname = '${T}';
" | tee "$OUT_DIR/${EXP}_after.txt"

pg -c "
SELECT calls, round(mean_exec_time::numeric,2) AS mean_ms,
       round(total_exec_time::numeric,2) AS total_ms
FROM pg_stat_statements
WHERE query ILIKE '%events%user_id%' AND query NOT ILIKE '%pg_stat%'
ORDER BY total_exec_time DESC LIMIT 3;
" | tee -a "$OUT_DIR/${EXP}_after.txt" || true

echo "[7] ВЕРИФИКАЦИЯ: цикл анализа, рекомендация должна ИСЧЕЗНУТЬ..."
wait_cycle
if has_rec "Missing index" && has_rec "$T"; then
  echo "  ⚠ Рекомендация всё ещё присутствует (проверь, что нагрузка после шла по индексу)."
else
  echo "  ✓ Рекомендация по '${T}' ИСЧЕЗЛА. Цикл замкнут."
fi
echo "  >>> Сделай СКРИНШОТ интерфейса без рекомендации (состояние 'ПОСЛЕ')."
echo ""
echo "ИТОГ Эксп.1: сравни out/${EXP}_before.txt и out/${EXP}_after.txt — mean_ms и seq_scan."
