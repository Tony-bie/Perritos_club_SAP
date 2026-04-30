-- =============================================================================
-- HANA Analytics - Bloque B: Optimizations (Índices)
-- =============================================================================
-- Objetivo: Añadir índices secundarios para acelerar consultas de negocio.
-- Ejecución: Después de 001_analytics_extension_tables.sql y 002_analytics_extension_views.sql
-- Idempotencia: Si el índice ya existe, se omite la creación.
-- Compatibilidad: Detecta dinámicamente los nombres de columnas existentes en HANA.
-- SQL puro: Ejecutable directamente en HANA Studio, hdbsql, o via Python.
-- =============================================================================

SET SCHEMA SOC_PIPELINE;

-- =========================================================================
-- Helper: escoger el primer nombre de columna existente entre varios candidatos.
-- =========================================================================

DO
BEGIN
    DECLARE v_idx_count INTEGER;
    DECLARE v_raw_ts NVARCHAR(128);
    DECLARE v_raw_type NVARCHAR(128);
    DECLARE v_raw_ip NVARCHAR(128);
    DECLARE v_raw_service NVARCHAR(128);
    DECLARE v_win_start NVARCHAR(128);
    DECLARE v_alert_time NVARCHAR(128);
    DECLARE v_alert_severity NVARCHAR(128);
    DECLARE v_alert_run NVARCHAR(128);
    DECLARE v_sql NVARCHAR(5000);

    -- RAW_LOGS: timestamp
    SELECT COALESCE(
        MAX(CASE WHEN COLUMN_NAME = 'LOG_TIMESTAMP_UTC' THEN COLUMN_NAME END),
        MAX(CASE WHEN COLUMN_NAME = 'EVENT_TIME' THEN COLUMN_NAME END)
    ) INTO v_raw_ts
    FROM SYS.TABLE_COLUMNS
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'RAW_LOGS'
      AND COLUMN_NAME IN ('LOG_TIMESTAMP_UTC', 'EVENT_TIME');

    -- RAW_LOGS: tipo de log
    SELECT COALESCE(
        MAX(CASE WHEN COLUMN_NAME = 'SAP_FUNCTION_LOG_TYPE' THEN COLUMN_NAME END),
        MAX(CASE WHEN COLUMN_NAME = 'SEVERITY' THEN COLUMN_NAME END)
    ) INTO v_raw_type
    FROM SYS.TABLE_COLUMNS
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'RAW_LOGS'
      AND COLUMN_NAME IN ('SAP_FUNCTION_LOG_TYPE', 'SEVERITY');

    -- RAW_LOGS: ip/host
    SELECT COALESCE(
        MAX(CASE WHEN COLUMN_NAME = 'CLIENT_IP' THEN COLUMN_NAME END),
        MAX(CASE WHEN COLUMN_NAME = 'SOURCE_HOST' THEN COLUMN_NAME END)
    ) INTO v_raw_ip
    FROM SYS.TABLE_COLUMNS
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'RAW_LOGS'
      AND COLUMN_NAME IN ('CLIENT_IP', 'SOURCE_HOST');

    -- RAW_LOGS: servicio
    SELECT COALESCE(
        MAX(CASE WHEN COLUMN_NAME = 'SERVICE_ID' THEN COLUMN_NAME END),
        MAX(CASE WHEN COLUMN_NAME = 'SERVICE_NAME' THEN COLUMN_NAME END)
    ) INTO v_raw_service
    FROM SYS.TABLE_COLUMNS
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'RAW_LOGS'
      AND COLUMN_NAME IN ('SERVICE_ID', 'SERVICE_NAME');

    -- WINDOW_METRICS: inicio de ventana
    SELECT COALESCE(
        MAX(CASE WHEN COLUMN_NAME = 'WINDOW_START_UTC' THEN COLUMN_NAME END),
        MAX(CASE WHEN COLUMN_NAME = 'WINDOW_START' THEN COLUMN_NAME END)
    ) INTO v_win_start
    FROM SYS.TABLE_COLUMNS
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'WINDOW_METRICS'
      AND COLUMN_NAME IN ('WINDOW_START_UTC', 'WINDOW_START');

    -- ALERTS_EVENTS: timestamp
    SELECT COALESCE(
        MAX(CASE WHEN COLUMN_NAME = 'DETECTED_AT_UTC' THEN COLUMN_NAME END),
        MAX(CASE WHEN COLUMN_NAME = 'EVENT_TIME' THEN COLUMN_NAME END)
    ) INTO v_alert_time
    FROM SYS.TABLE_COLUMNS
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'ALERTS_EVENTS'
      AND COLUMN_NAME IN ('DETECTED_AT_UTC', 'EVENT_TIME');

    -- ALERTS_EVENTS: severidad
    SELECT MAX(CASE WHEN COLUMN_NAME = 'SEVERITY' THEN COLUMN_NAME END)
      INTO v_alert_severity
    FROM SYS.TABLE_COLUMNS
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'ALERTS_EVENTS'
      AND COLUMN_NAME = 'SEVERITY';

    -- ALERTS_EVENTS: run
    SELECT MAX(CASE WHEN COLUMN_NAME = 'RUN_ID' THEN COLUMN_NAME END)
      INTO v_alert_run
    FROM SYS.TABLE_COLUMNS
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'ALERTS_EVENTS'
      AND COLUMN_NAME = 'RUN_ID';

    -- Índice 1: RAW_LOGS timestamp/type/ip
    SELECT COUNT(*) INTO v_idx_count
    FROM SYS.INDEXES
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND INDEX_NAME = 'RAW_LOGS_TIMESTAMP_TYPE_IP_IDX';

    IF :v_idx_count = 0 AND :v_raw_ts IS NOT NULL AND :v_raw_type IS NOT NULL AND :v_raw_ip IS NOT NULL THEN
        v_sql := 'CREATE INDEX "RAW_LOGS_TIMESTAMP_TYPE_IP_IDX" ON "SOC_PIPELINE"."RAW_LOGS" ("' || :v_raw_ts || '", "' || :v_raw_type || '", "' || :v_raw_ip || '")';
        EXECUTE IMMEDIATE :v_sql;
    END IF;

    -- Índice 2: RAW_LOGS service/time
    SELECT COUNT(*) INTO v_idx_count
    FROM SYS.INDEXES
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND INDEX_NAME = 'RAW_LOGS_SERVICE_TIME_IDX';

    IF :v_idx_count = 0 AND :v_raw_service IS NOT NULL AND :v_raw_ts IS NOT NULL THEN
        v_sql := 'CREATE INDEX "RAW_LOGS_SERVICE_TIME_IDX" ON "SOC_PIPELINE"."RAW_LOGS" ("' || :v_raw_service || '", "' || :v_raw_ts || '")';
        EXECUTE IMMEDIATE :v_sql;
    END IF;

    -- Índice 3: WINDOW_METRICS run/window
    SELECT COUNT(*) INTO v_idx_count
    FROM SYS.INDEXES
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND INDEX_NAME = 'WINDOW_METRICS_RUN_WINDOW_IDX';

    IF :v_idx_count = 0 AND :v_win_start IS NOT NULL THEN
        v_sql := 'CREATE INDEX "WINDOW_METRICS_RUN_WINDOW_IDX" ON "SOC_PIPELINE"."WINDOW_METRICS" ("RUN_ID", "' || :v_win_start || '")';
        EXECUTE IMMEDIATE :v_sql;
    END IF;

    -- Índice 4: ALERTS_EVENTS time/severity/run
    SELECT COUNT(*) INTO v_idx_count
    FROM SYS.INDEXES
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND INDEX_NAME = 'ALERTS_EVENTS_TIME_SEVERITY_IDX';

    IF :v_idx_count = 0 AND :v_alert_time IS NOT NULL AND :v_alert_severity IS NOT NULL AND :v_alert_run IS NOT NULL THEN
        v_sql := 'CREATE INDEX "ALERTS_EVENTS_TIME_SEVERITY_IDX" ON "SOC_PIPELINE"."ALERTS_EVENTS" ("' || :v_alert_time || '", "' || :v_alert_severity || '", "' || :v_alert_run || '")';
        EXECUTE IMMEDIATE :v_sql;
    END IF;
END;

-- =============================================================================
-- Validación manual recomendada:
--
-- SELECT INDEX_NAME, TABLE_NAME, COLUMN_NAME, POSITION
-- FROM SYS.INDEX_COLUMNS
-- WHERE SCHEMA_NAME = 'SOC_PIPELINE'
--   AND INDEX_NAME IN (
--     'RAW_LOGS_TIMESTAMP_TYPE_IP_IDX',
--     'RAW_LOGS_SERVICE_TIME_IDX',
--     'WINDOW_METRICS_RUN_WINDOW_IDX',
--     'ALERTS_EVENTS_TIME_SEVERITY_IDX'
--   )
-- ORDER BY TABLE_NAME, INDEX_NAME, POSITION;
-- =============================================================================
