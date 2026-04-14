# PostgreSQL Monitoring Demo

Проект по мониторингу производительности PostgreSQL.

## Цель проекта

Построить систему мониторинга PostgreSQL, которая позволяет:
- Собирать ключевые метрики производительности
- Выявлять узкие места и медленные запросы
- Мониторить влияние приложений на базу данных
- Настраивать алерты на проблемные ситуации

## Архитектура стека

Проект построен с использованием Docker Compose и включает следующие компоненты:

- **PostgreSQL 16** — основная база данных с тестовыми данными (~3.7 млн строк в 5 связанных таблицах)
- **pgAdmin 4** — удобный веб-интерфейс для работы с базой
- **postgres_exporter** — экспортирует метрики PostgreSQL в формате Prometheus (включая pg_stat_statements)
- **Prometheus** — система сбора и хранения метрик + alerting rules
- **Grafana** — визуализация метрик и дашборды
- **FastAPI Load Simulator** — простое приложение для генерации нагрузки на базу

## Что было реализовано

### 1. PostgreSQL
- Настроен `postgresql.conf` (shared_buffers, work_mem, autovacuum и др.)
- Подключено расширение `pg_stat_statements`

### 2. Мониторинг
- Поднят стек Prometheus + postgres_exporter
- postgres_exporter настроен на сбор pg_stat_statements
- Настроены alerting rules:
  - HighConnectionCount
  - LowCacheHitRatio
  - SlowQueries
  - HighWALGenerationRate
- Импортированы готовые дашборды в Grafana
- Создан собственный небольшой дашборд, ещё будет дорабатываться

### 3. Нагрузочное тестирование
- Разработано простое FastAPI-приложение (`app-load`)
- Реализованы разные уровни нагрузки (simple / medium / heavy запросы)

### 4. Дашборд в Grafana
![img.png](img.png)
