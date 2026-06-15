#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Общие настройки для всех экспериментов. Меняй ТОЛЬКО здесь, если на стенде
# другие имена/порты/значения. Все остальные скрипты берут параметры отсюда.
# ─────────────────────────────────────────────────────────────────────────────

# Имя docker-контейнера с PostgreSQL (из docker-compose: container_name: postgres)
export PG_CONTAINER="postgres"

# Доступы к БД (ДОЛЖНЫ совпадать с .env стенда — POSTGRES_DB / POSTGRES_USER).
# Проверь свой .env и при необходимости поменяй значения ниже.
export DB_NAME="${POSTGRES_DB:-dvdrental}"
export DB_USER="${POSTGRES_USER:-admin}"
# пароль не нужен: ходим внутрь контейнера через docker exec, там local-доступ

# Адрес HTTP-интерфейса сервиса pg-advisor
export ADVISOR_URL="http://localhost:9188"

# Сколько секунд один цикл анализа (docker-compose: ANALYSIS_INTERVAL_SEC)
# Берём 60. Если оставишь дефолтные 900 — поменяй здесь на 900.
export CYCLE_SEC="60"

# Куда складывать собранные результаты (метрики до/после)
export OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/out"
mkdir -p "$OUT_DIR"

# ── Вспомогательные функции ──────────────────────────────────────────────────

# Выполнить SQL в контейнере, выровненный вывод (для скриншотов/логов)
pg() {
  docker exec -i "$PG_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -P pager=off "$@"
}

# Выполнить SQL и вернуть одно скалярное значение без рамок (для расчётов)
pg_scalar() {
  docker exec -i "$PG_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tA -c "$1"
}

# Дождаться следующего цикла анализа сервиса.
# Предпочтительно дёрнуть /recompute (мгновенный внеплановый прогон),
# иначе просто спим один интервал.
wait_cycle() {
  echo "→ Триггерю внеплановый анализ через POST /recompute ..."
  if curl -fs -X POST "$ADVISOR_URL/recompute" >/dev/null 2>&1; then
    echo "  /recompute принят, жду 5 с на завершение цикла."
    sleep 5
  else
    echo "  /recompute недоступен, сплю полный цикл ${CYCLE_SEC}s."
    sleep "$CYCLE_SEC"
  fi
}

# Достать рекомендации сервиса в JSON (для проверки наличия/отсутствия)
fetch_recs() {
  curl -fs "$ADVISOR_URL/recommendations" 2>/dev/null || echo "[]"
}

# Проверить, есть ли в рекомендациях запись по подстроке (категория/таблица).
# Возвращает 0 (есть) или 1 (нет). Использует grep по сырому JSON — достаточно
# для эксперимента, не требует jq.
has_rec() {
  local needle="$1"
  fetch_recs | grep -qi "$needle"
}

echo "[env] PG_CONTAINER=$PG_CONTAINER DB=$DB_NAME USER=$DB_USER ADVISOR=$ADVISOR_URL CYCLE=${CYCLE_SEC}s"
echo "[env] OUT_DIR=$OUT_DIR"
