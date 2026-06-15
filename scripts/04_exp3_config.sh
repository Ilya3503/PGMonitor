#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ЭКСПЕРИМЕНТ 3 — НЕПОДХОДЯЩАЯ КОНФИГУРАЦИЯ (shared_buffers)
# Особенность: требует РЕСТАРТА контейнера с разным shared_buffers,
# поэтому делится на две фазы. Запускай с аргументом before|after.
#
#   Фаза 1:  выставь shared_buffers=128MB в configs/postgres/postgresql.conf,
#            docker compose up -d postgres,  затем  ./04_exp3_config.sh before
#   Фаза 2:  верни shared_buffers=1536MB (25% от 6144 = норма),
#            docker compose up -d postgres,  затем  ./04_exp3_config.sh after
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
source ./00_env.sh

PHASE="${1:-}"
EXP="exp3"
if [ "$PHASE" != "before" ] && [ "$PHASE" != "after" ]; then
  echo "Использование: $0 before|after"
  exit 1
fi

echo "== ЭКСПЕРИМЕНТ 3, фаза: ${PHASE} =="

echo "[1] Текущее значение shared_buffers:"
pg -c "SHOW shared_buffers;"

echo "[2] Сбрасываю статистику БД и прогреваю нагрузкой (3 мин)..."
pg -c "SELECT pg_stat_reset();" >/dev/null
# смешанная нагрузка: точечные выборки + агрегации по реальным таблицам
( ./gen_load.sh 180 4 ) &
LOADPID=$!
# параллельно несколько агрегаций, чтобы задеть кэш
for _ in $(seq 1 30); do
  pg -c "SELECT count(*), avg(price) FROM order_items;" >/dev/null 2>&1 || true
  sleep 5
done
wait $LOADPID 2>/dev/null || true

echo "[3] Cache hit ratio (out/${EXP}_${PHASE}.txt):"
pg -c "
SELECT datname,
       blks_hit, blks_read,
       round(100.0*blks_hit/NULLIF(blks_hit+blks_read,0), 2) AS cache_hit_pct
FROM pg_stat_database WHERE datname='${DB_NAME}';
" | tee "$OUT_DIR/${EXP}_${PHASE}.txt"

if [ "$PHASE" = "before" ]; then
  echo "[4] ДЕТЕКТ: цикл анализа, ждём рекомендацию config/shared_buffers..."
  wait_cycle
  if has_rec "shared_buffers"; then
    echo "  ✓ Сервис выдал рекомендацию по shared_buffers."
  else
    echo "  ⚠ Нет рекомендации. Проверь TOTAL_RAM_MB в окружении pg-advisor"
    echo "    (должно быть 6144, иначе целевое значение посчитается неверно)."
    fetch_recs
  fi
  echo "  >>> СКРИНШОТ интерфейса с рекомендацией config (состояние 'ДО')."
  echo ""
  echo "  Теперь: правь shared_buffers на 1536MB, перезапусти postgres,"
  echo "  и запусти:  ./04_exp3_config.sh after"
else
  echo "[4] ВЕРИФИКАЦИЯ: цикл анализа, рекомендация должна исчезнуть..."
  wait_cycle
  if has_rec "shared_buffers"; then
    echo "  ⚠ Рекомендация ещё есть — проверь, что новое значение применилось (SHOW shared_buffers)."
  else
    echo "  ✓ Рекомендация по shared_buffers исчезла."
  fi
  echo "  >>> СКРИНШОТ интерфейса без рекомендации (состояние 'ПОСЛЕ')."
  echo ""
  echo "ИТОГ Эксп.3: сравни cache_hit_pct в out/${EXP}_before.txt и out/${EXP}_after.txt."
fi
