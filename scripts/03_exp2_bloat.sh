#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ЭКСПЕРИМЕНТ 2 — РАЗДУТИЕ ТАБЛИЦЫ  (order_items, ~1.5 млн строк)
# Цикл: отключаем автовакуум → 10× массовый UPDATE → детект bloat →
#       VACUUM ANALYZE → верификация.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
source ./00_env.sh

T="order_items"
EXP="exp2"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║ ЭКСПЕРИМЕНТ 2: раздутие таблицы ${T}                       "
echo "╚══════════════════════════════════════════════════════════╝"

echo "[1] Отключаю автовакуум на таблице (моделируем отставание очистки)."
echo "    Причина: MVCC оставляет мёртвые версии строк; без вакуума физический"
echo "    размер растёт быстрее объёма актуальных данных — это и есть bloat."
pg -c "ALTER TABLE ${T} SET (autovacuum_enabled = false);"

echo "[2] Метрики ДО (out/${EXP}_before.txt):"
pg -c "
SELECT relname, n_live_tup, n_dead_tup,
       CASE WHEN n_live_tup+n_dead_tup>0
            THEN round(100.0*n_dead_tup/(n_live_tup+n_dead_tup),1) ELSE 0 END AS dead_pct,
       pg_size_pretty(pg_relation_size(relid)) AS heap_size
FROM pg_stat_user_tables WHERE relname='${T}';
" | tee "$OUT_DIR/${EXP}_before.txt"

echo "[3] Запускаю 10 итераций массового UPDATE (~10% строк каждая)..."
for i in $(seq 1 10); do
  echo "    итерация $i/10"
  pg -c "UPDATE ${T} SET price = price + 0.01 WHERE id % 10 = ${i} % 10;" >/dev/null
done

echo "[4] Метрики после UPDATE (раздутие должно вырасти):"
pg -c "
SELECT relname, n_live_tup, n_dead_tup,
       CASE WHEN n_live_tup+n_dead_tup>0
            THEN round(100.0*n_dead_tup/(n_live_tup+n_dead_tup),1) ELSE 0 END AS dead_pct,
       pg_size_pretty(pg_relation_size(relid)) AS heap_size
FROM pg_stat_user_tables WHERE relname='${T}';
" | tee -a "$OUT_DIR/${EXP}_before.txt"

echo "[5] ДЕТЕКТ: обновляю статистику и запускаю цикл анализа..."
echo "    (ANALYZE нужен: оценка bloat в сервисе считается по pg_stats)"
pg -c "ANALYZE ${T};" >/dev/null
wait_cycle
if has_rec "loat" && has_rec "$T"; then
  echo "  ✓ Сервис выдал рекомендацию о раздутии '${T}'."
else
  echo "  ⚠ Нет рекомендации. Проверь пороги BLOAT_RATIO_WARN/BLOAT_MIN_SIZE_MB."
  fetch_recs
fi
echo "  >>> СКРИНШОТ интерфейса с рекомендацией bloat (состояние 'ДО')."
read -rp "  Enter, когда скриншот сделан..."

echo "[6] ПРИМЕНЕНИЕ: VACUUM ANALYZE ${T} (команда из вывода сервиса)."
pg -c "VACUUM (ANALYZE, VERBOSE) ${T};" 2>&1 | tail -5

echo "[7] Метрики ПОСЛЕ (out/${EXP}_after.txt):"
echo "    NB: VACUUM без FULL НЕ возвращает место в ОС — heap_size может не упасть,"
echo "    но n_dead_tup обнулится и оценка сервиса перестанет считать таблицу раздутой."
pg -c "
SELECT relname, n_live_tup, n_dead_tup,
       CASE WHEN n_live_tup+n_dead_tup>0
            THEN round(100.0*n_dead_tup/(n_live_tup+n_dead_tup),1) ELSE 0 END AS dead_pct,
       pg_size_pretty(pg_relation_size(relid)) AS heap_size
FROM pg_stat_user_tables WHERE relname='${T}';
" | tee "$OUT_DIR/${EXP}_after.txt"

echo "[8] ВЕРИФИКАЦИЯ: цикл анализа, рекомендация bloat должна исчезнуть..."
wait_cycle
if has_rec "loat" && has_rec "$T"; then
  echo "  ⚠ Рекомендация ещё есть (оценочная формула может отставать на 1 запись/ANALYZE)."
else
  echo "  ✓ Рекомендация bloat по '${T}' исчезла."
fi
echo "  >>> СКРИНШОТ интерфейса без рекомендации."

echo "[9] Возвращаю автовакуум."
pg -c "ALTER TABLE ${T} RESET (autovacuum_enabled);"
echo "ИТОГ Эксп.2: сравни dead_pct и heap_size в before/after."
