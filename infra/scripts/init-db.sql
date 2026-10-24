-- Инициализация демо-базы: расширение PostGIS обязательно до первых миграций.
CREATE EXTENSION IF NOT EXISTS postgis;

-- Расширения для статистики запросов полезны при проверке цели «до 2 секунд».
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
