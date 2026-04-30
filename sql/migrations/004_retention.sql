-- =============================================================================
-- HANA Analytics - Bloque B: Retención y Limpieza Automática
-- =============================================================================
-- Objetivo: Definir tabla AUDIT_LOG y stored procedure para limpieza de datos antiguos.
-- Ejecución: Después de 003_optimizations.sql.
-- Compatibilidad: Detecta dinámicamente los nombres de columnas existentes en HANA.
-- SQL puro + SQLScript: Script mixto para crear objetos y luego definir lógica.
-- =============================================================================

SET SCHEMA SOC_PIPELINE;

-- =============================================================================
-- PASO 1: Crear tabla AUDIT_LOG si no existe
-- =============================================================================
DO
BEGIN
    DECLARE v_count INTEGER;

    SELECT COUNT(*) INTO v_count
    FROM SYS.TABLES
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'AUDIT_LOG';

    IF :v_count = 0 THEN
        EXECUTE IMMEDIATE '
            CREATE COLUMN TABLE "SOC_PIPELINE"."AUDIT_LOG" (
                "LOG_ID" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                "TIMESTAMP" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                "OPERATION" NVARCHAR(255),
                "DETAILS" NVARCHAR(4000),
                "LEVEL" NVARCHAR(50) DEFAULT ''INFO''
            )
        ';
    END IF;
END;

DO
BEGIN
    DECLARE v_count INTEGER;

    SELECT COUNT(*) INTO v_count
    FROM SYS.INDEXES
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND INDEX_NAME = 'AUDIT_LOG_TS_IDX';

    IF :v_count = 0 THEN
        EXECUTE IMMEDIATE 'CREATE INDEX "AUDIT_LOG_TS_IDX" ON "SOC_PIPELINE"."AUDIT_LOG" ("TIMESTAMP")';
    END IF;
END;

-- =============================================================================
-- PASO 2: Crear o reemplazar Stored Procedure sp_cleanup_old_data
-- =============================================================================

CREATE OR REPLACE PROCEDURE "SOC_PIPELINE"."sp_cleanup_old_data"(
    IN p_retention_days INT DEFAULT 90
)
LANGUAGE SQLSCRIPT
AS
BEGIN
    DECLARE v_cutoff_time TIMESTAMP;
    DECLARE v_cutoff_text NVARCHAR(40);
    DECLARE v_rows_deleted INT := 0;
    DECLARE v_alert_time NVARCHAR(128);
    DECLARE v_window_time NVARCHAR(128);
    DECLARE v_raw_time NVARCHAR(128);
    DECLARE v_has_ingest_runs INT := 0;
    DECLARE v_ingest_completed NVARCHAR(128);
    DECLARE v_sql NVARCHAR(5000);

    v_cutoff_time := ADD_DAYS(CURRENT_TIMESTAMP, -p_retention_days);
    v_cutoff_text := TO_NVARCHAR(:v_cutoff_time, 'YYYY-MM-DD HH24:MI:SS');

        SELECT COALESCE(
                MAX(CASE WHEN COLUMN_NAME = 'DETECTED_AT_UTC' THEN COLUMN_NAME END),
                MAX(CASE WHEN COLUMN_NAME = 'EVENT_TIME' THEN COLUMN_NAME END)
        ) INTO v_alert_time
        FROM SYS.TABLE_COLUMNS
        WHERE SCHEMA_NAME = CURRENT_SCHEMA
            AND TABLE_NAME = 'ALERTS_EVENTS'
            AND COLUMN_NAME IN ('DETECTED_AT_UTC', 'EVENT_TIME');

        SELECT COALESCE(
                MAX(CASE WHEN COLUMN_NAME = 'WINDOW_START_UTC' THEN COLUMN_NAME END),
                MAX(CASE WHEN COLUMN_NAME = 'WINDOW_START' THEN COLUMN_NAME END)
        ) INTO v_window_time
        FROM SYS.TABLE_COLUMNS
        WHERE SCHEMA_NAME = CURRENT_SCHEMA
            AND TABLE_NAME = 'WINDOW_METRICS'
            AND COLUMN_NAME IN ('WINDOW_START_UTC', 'WINDOW_START');

        SELECT COALESCE(
                MAX(CASE WHEN COLUMN_NAME = 'LOG_TIMESTAMP_UTC' THEN COLUMN_NAME END),
                MAX(CASE WHEN COLUMN_NAME = 'EVENT_TIME' THEN COLUMN_NAME END)
        ) INTO v_raw_time
        FROM SYS.TABLE_COLUMNS
        WHERE SCHEMA_NAME = CURRENT_SCHEMA
            AND TABLE_NAME = 'RAW_LOGS'
            AND COLUMN_NAME IN ('LOG_TIMESTAMP_UTC', 'EVENT_TIME');

    SELECT COUNT(*) INTO v_has_ingest_runs
    FROM SYS.TABLES
    WHERE SCHEMA_NAME = CURRENT_SCHEMA
      AND TABLE_NAME = 'INGEST_RUNS';

        IF :v_has_ingest_runs > 0 THEN
                SELECT COALESCE(
                        MAX(CASE WHEN COLUMN_NAME = 'COMPLETED_AT_UTC' THEN COLUMN_NAME END),
                        MAX(CASE WHEN COLUMN_NAME = 'COMPLETED_AT' THEN COLUMN_NAME END)
                ) INTO v_ingest_completed
                FROM SYS.TABLE_COLUMNS
                WHERE SCHEMA_NAME = CURRENT_SCHEMA
                    AND TABLE_NAME = 'INGEST_RUNS'
                    AND COLUMN_NAME IN ('COMPLETED_AT_UTC', 'COMPLETED_AT');
        END IF;

    INSERT INTO "SOC_PIPELINE"."AUDIT_LOG" ("TIMESTAMP", "OPERATION", "DETAILS", "LEVEL")
    VALUES (CURRENT_TIMESTAMP, 'sp_cleanup_old_data',
            'Iniciando limpieza. Cutoff: ' || :v_cutoff_text, 'INFO');

    -- Fase 1: alertas antiguas
    IF :v_alert_time IS NOT NULL THEN
        v_sql := 'DELETE FROM "SOC_PIPELINE"."ALERTS_EVENTS" WHERE "' || :v_alert_time || '" < ''' || :v_cutoff_text || '''';
        EXECUTE IMMEDIATE :v_sql;
        v_rows_deleted := ::ROWCOUNT;

        INSERT INTO "SOC_PIPELINE"."AUDIT_LOG" ("TIMESTAMP", "OPERATION", "DETAILS", "LEVEL")
        VALUES (CURRENT_TIMESTAMP, 'sp_cleanup_old_data',
                'Deleted ' || v_rows_deleted || ' ALERTS_EVENTS rows', 'INFO');
    END IF;

    -- Fase 2: métricas antiguas
    IF :v_window_time IS NOT NULL THEN
        v_sql := 'DELETE FROM "SOC_PIPELINE"."WINDOW_METRICS" WHERE "' || :v_window_time || '" < ''' || :v_cutoff_text || '''';
        EXECUTE IMMEDIATE :v_sql;
        v_rows_deleted := ::ROWCOUNT;

        INSERT INTO "SOC_PIPELINE"."AUDIT_LOG" ("TIMESTAMP", "OPERATION", "DETAILS", "LEVEL")
        VALUES (CURRENT_TIMESTAMP, 'sp_cleanup_old_data',
                'Deleted ' || v_rows_deleted || ' WINDOW_METRICS rows', 'INFO');
    END IF;

    -- Fase 3: logs brutos antiguos
    IF :v_raw_time IS NOT NULL THEN
        v_sql := 'DELETE FROM "SOC_PIPELINE"."RAW_LOGS" WHERE "' || :v_raw_time || '" < ''' || :v_cutoff_text || '''';
        EXECUTE IMMEDIATE :v_sql;
        v_rows_deleted := ::ROWCOUNT;

        INSERT INTO "SOC_PIPELINE"."AUDIT_LOG" ("TIMESTAMP", "OPERATION", "DETAILS", "LEVEL")
        VALUES (CURRENT_TIMESTAMP, 'sp_cleanup_old_data',
                'Deleted ' || v_rows_deleted || ' RAW_LOGS rows', 'INFO');
    END IF;

    -- Fase 4: cleanup de runs huérfanos
    IF :v_has_ingest_runs > 0 THEN
        IF :v_ingest_completed IS NOT NULL THEN
            v_sql := 'DELETE FROM "SOC_PIPELINE"."MODEL_RUNS" WHERE "RUN_ID" NOT IN (' ||
                     'SELECT DISTINCT "RUN_ID" FROM "SOC_PIPELINE"."WINDOW_METRICS" ' ||
                     'UNION ALL ' ||
                     'SELECT DISTINCT "RUN_ID" FROM "SOC_PIPELINE"."ALERTS_EVENTS") ' ||
                     'AND "RUN_ID" NOT IN (' ||
                     'SELECT DISTINCT "RUN_ID" FROM "SOC_PIPELINE"."INGEST_RUNS" WHERE "' || :v_ingest_completed || '" > ''' || :v_cutoff_text || '''' ||
                     ')';
            EXECUTE IMMEDIATE :v_sql;
        ELSE
            DELETE FROM "SOC_PIPELINE"."MODEL_RUNS"
            WHERE "RUN_ID" NOT IN (
                SELECT DISTINCT "RUN_ID" FROM "SOC_PIPELINE"."WINDOW_METRICS"
                UNION ALL
                SELECT DISTINCT "RUN_ID" FROM "SOC_PIPELINE"."ALERTS_EVENTS"
            );
        END IF;
    ELSE
        DELETE FROM "SOC_PIPELINE"."MODEL_RUNS"
        WHERE "RUN_ID" NOT IN (
            SELECT DISTINCT "RUN_ID" FROM "SOC_PIPELINE"."WINDOW_METRICS"
            UNION ALL
            SELECT DISTINCT "RUN_ID" FROM "SOC_PIPELINE"."ALERTS_EVENTS"
        );
    END IF;

    v_rows_deleted := ::ROWCOUNT;
    INSERT INTO "SOC_PIPELINE"."AUDIT_LOG" ("TIMESTAMP", "OPERATION", "DETAILS", "LEVEL")
    VALUES (CURRENT_TIMESTAMP, 'sp_cleanup_old_data',
            'Deleted ' || v_rows_deleted || ' orphaned MODEL_RUNS rows', 'INFO');

    INSERT INTO "SOC_PIPELINE"."AUDIT_LOG" ("TIMESTAMP", "OPERATION", "DETAILS", "LEVEL")
    VALUES (CURRENT_TIMESTAMP, 'sp_cleanup_old_data',
            'Cleanup completed for retention_days=' || p_retention_days, 'INFO');
END;

-- =============================================================================
-- Validación manual recomendada:
--
-- SELECT * FROM "SOC_PIPELINE"."AUDIT_LOG" ORDER BY "TIMESTAMP" DESC LIMIT 10;
-- SELECT PROCEDURE_NAME FROM SYS.PROCEDURES
-- WHERE SCHEMA_NAME = 'SOC_PIPELINE' AND PROCEDURE_NAME = 'sp_cleanup_old_data';
-- CALL "SOC_PIPELINE"."sp_cleanup_old_data"(p_retention_days => 999);
-- =============================================================================
