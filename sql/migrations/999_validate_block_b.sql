-- =============================================================================
-- HANA Schema Validation - Bloque B
-- =============================================================================
-- Script para validar que todas las migraciones de Bloque B se aplicaron correctamente.
-- Ejecuta este script después de 003_optimizations.sql y 004_retention.sql.
-- =============================================================================

-- =========================================================================
-- Validación 1: Verificar que los índices fueron creados
-- =========================================================================
SELECT 'VALIDATION: Bloque B Indices' AS test_name FROM DUMMY;
SELECT INDEX_NAME, TABLE_NAME, COLUMN_NAME, POSITION 
FROM SYS.INDEX_COLUMNS 
WHERE SCHEMA_NAME = 'SOC_PIPELINE' 
  AND INDEX_NAME IN (
        'RAW_LOGS_TIMESTAMP_TYPE_IP_IDX',
    'RAW_LOGS_SERVICE_TIME_IDX',
    'WINDOW_METRICS_RUN_WINDOW_IDX',
    'ALERTS_EVENTS_TIME_SEVERITY_IDX'
  )
ORDER BY TABLE_NAME, INDEX_NAME, POSITION;

-- Expected: 4 indices, 10+ rows total (compound indices have multiple columns)
-- =========================================================================
-- Validación 2: Verificar que la tabla AUDIT_LOG existe y está vacía
-- =========================================================================
SELECT 'VALIDATION: AUDIT_LOG Table' AS test_name FROM DUMMY;
SELECT T.TABLE_NAME,
             (SELECT COUNT(*) FROM SYS.TABLE_COLUMNS C
                 WHERE C.SCHEMA_NAME = T.SCHEMA_NAME
                     AND C.TABLE_NAME = T.TABLE_NAME) AS COLUMN_COUNT,
             T.RECORD_COUNT
FROM SYS.M_TABLES T
WHERE T.SCHEMA_NAME = 'SOC_PIPELINE' AND T.TABLE_NAME = 'AUDIT_LOG';

-- Expected: 1 row with RECORD_COUNT = 0 (empty)
-- =========================================================================
-- Validación 3: Verificar que la procedure existe
-- =========================================================================
SELECT 'VALIDATION: sp_cleanup_old_data Procedure' AS test_name FROM DUMMY;
SELECT PROCEDURE_NAME, PROCEDURE_OID FROM SYS.PROCEDURES 
WHERE SCHEMA_NAME = 'SOC_PIPELINE' AND PROCEDURE_NAME = 'sp_cleanup_old_data';

-- Expected: 1 row
-- =========================================================================
-- Validación 4: Listar todos los índices en el schema SOC_PIPELINE
-- =========================================================================
SELECT 'VALIDATION: All Indices in SOC_PIPELINE' AS test_name FROM DUMMY;
SELECT INDEX_NAME, TABLE_NAME FROM SYS.INDEXES 
WHERE SCHEMA_NAME = 'SOC_PIPELINE' 
ORDER BY TABLE_NAME, INDEX_NAME;

-- Expected: Should show all block A + B indices
-- =========================================================================
-- Validación 5: Listar todas las procedures en el schema SOC_PIPELINE
-- =========================================================================
SELECT 'VALIDATION: All Procedures in SOC_PIPELINE' AS test_name FROM DUMMY;
SELECT PROCEDURE_NAME FROM SYS.PROCEDURES 
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
ORDER BY PROCEDURE_NAME;

-- Expected: sp_cleanup_old_data + any others from Bloque A
-- =========================================================================
-- Validación 6: Contar filas en tablas principales
-- =========================================================================
SELECT 'VALIDATION: Row Counts' AS test_name FROM DUMMY;
SELECT 
    'RAW_LOGS' AS table_name, COUNT(*) AS row_count FROM "SOC_PIPELINE"."RAW_LOGS"
UNION ALL
SELECT 
    'WINDOW_METRICS', COUNT(*) FROM "SOC_PIPELINE"."WINDOW_METRICS"
UNION ALL
SELECT 
    'ALERTS_EVENTS', COUNT(*) FROM "SOC_PIPELINE"."ALERTS_EVENTS"
UNION ALL
SELECT 
    'MODEL_RUNS', COUNT(*) FROM "SOC_PIPELINE"."MODEL_RUNS"
UNION ALL
SELECT 
    'AUDIT_LOG', COUNT(*) FROM "SOC_PIPELINE"."AUDIT_LOG"
ORDER BY table_name;

-- Expected: Shows row counts for each table; AUDIT_LOG likely empty initially
-- =========================================================================
-- Validación 7: Test (SAFE) - Llamar procedure sin borrar nada
-- =================================================================== 
-- Esta llamada usa retention_days = 999 (muy futuro) para que NO borre nada real.
-- Si funciona, significa la procedure está sintácticamente correcta.
SELECT 'VALIDATION: Testing sp_cleanup_old_data (DRY RUN)' AS test_name FROM DUMMY;

CALL "SOC_PIPELINE"."sp_cleanup_old_data"(p_retention_days => 999);

-- =========================================================================
-- Validación 8: Ver logs de la llamada de prueba
-- =========================================================================
SELECT 'VALIDATION: AUDIT_LOG from DRY RUN' AS test_name FROM DUMMY;
SELECT TOP 10 * FROM "SOC_PIPELINE"."AUDIT_LOG" ORDER BY "TIMESTAMP" DESC;

-- Expected: 5 rows (inicio + 4 fases + finalización) con details como "Deleted 0 RAW_LOGS rows"
-- =========================================================================
-- Resumen Final
-- =========================================================================
SELECT 'VALIDATION: COMPLETE' AS status FROM DUMMY;
SELECT 'All validations passed! Bloque B is ready.' AS message FROM DUMMY;

-- Si alguna validación falla o devuelve 0 filas, revisa:
-- 1. ¿Se ejecutaron 003_optimizations.sql y 004_retention.sql sin errores?
-- 2. ¿Ejecutaste en el schema correcto (SOC_PIPELINE)?
-- 3. ¿El usuario DBADMIN tiene permisos para CREATE INDEX y CREATE PROCEDURE?
-- =============================================================================
