#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Генератор нагрузки для Эксп.1. Шлёт SELECT * FROM events WHERE user_id = ?
# в несколько параллельных потоков в течение заданного времени.
# Если у тебя уже есть сервис app-load — можешь использовать его вместо этого.
# Использование:  ./gen_load.sh <секунд> <потоков>
# По умолчанию:   300 секунд, 4 потока
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
source ./00_env.sh

DURATION="${1:-300}"
THREADS="${2:-4}"

echo "== Нагрузка: ${DURATION}s, потоков: ${THREADS} =="

one_thread() {
  local deadline=$(( $(date +%s) + DURATION ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    local uid=$(( RANDOM % 100000 + 1 ))
    docker exec -i "$PG_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tA \
      -c "SELECT count(*) FROM events WHERE user_id = ${uid};" >/dev/null 2>&1
  done
}

for i in $(seq 1 "$THREADS"); do
  one_thread &
done
wait
echo "Нагрузка завершена."
