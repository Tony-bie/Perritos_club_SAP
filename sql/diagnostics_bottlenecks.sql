-- SAP SOC pipeline diagnostics and bottleneck checks.
-- Run against SAP HANA. All queries are read-only.
-- Default schema used by the app: SOC_PIPELINE.

-- ============================================================================
-- 1) Schema shape: confirms which runtime columns actually exist.
-- ============================================================================
SELECT '01_SCHEMA_COLUMNS' AS SECTION FROM DUMMY;

SELECT
    TABLE_NAME,
    POSITION,
    COLUMN_NAME,
    DATA_TYPE_NAME,
    LENGTH,
    IS_NULLABLE
FROM SYS.TABLE_COLUMNS
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
  AND TABLE_NAME IN (
      'RAW_LOGS',
      'INGEST_RUNS',
      'WINDOW_METRICS',
      'WINDOW_FEATURES',
      'ALERTS_EVENTS',
      'MODEL_RUNS',
      'MODEL_PREDICTIONS',
      'MODEL_SCORES'
  )
ORDER BY TABLE_NAME, POSITION;

-- ============================================================================
-- 2) Table sizes and memory footprint: first place to spot growth hot spots.
-- ============================================================================
SELECT '02_TABLE_SIZE_AND_MEMORY' AS SECTION FROM DUMMY;

SELECT
    TABLE_NAME,
    RECORD_COUNT,
    ROUND(MEMORY_SIZE_IN_TOTAL / 1024 / 1024, 2) AS MEMORY_MB,
    ROUND(MEMORY_SIZE_IN_MAIN / 1024 / 1024, 2) AS MAIN_MEMORY_MB,
    ROUND(MEMORY_SIZE_IN_DELTA / 1024 / 1024, 2) AS DELTA_MEMORY_MB
FROM SYS.M_CS_TABLES
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
ORDER BY MEMORY_SIZE_IN_TOTAL DESC;

-- ============================================================================
-- 3) Index inventory: validates expected performance helpers are present.
-- ============================================================================
SELECT '03_INDEX_INVENTORY' AS SECTION FROM DUMMY;

SELECT
    INDEX_NAME,
    TABLE_NAME,
    COLUMN_NAME,
    POSITION
FROM SYS.INDEX_COLUMNS
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
ORDER BY TABLE_NAME, INDEX_NAME, POSITION;

-- ============================================================================
-- 4) Latest ingestion runs: status, duration, page mismatch, and record mismatch.
-- ============================================================================
SELECT '04_LATEST_INGEST_RUNS' AS SECTION FROM DUMMY;

SELECT
    RUN_ID,
    STATUS,
    STARTED_AT_UTC,
    ENDED_AT_UTC,
    DURATION_SECONDS,
    TOTAL_PAGES_EXPECTED,
    TOTAL_PAGES_FETCHED,
    TOTAL_RECORDS_INFO,
    TOTAL_RECORDS_FETCHED,
    CASE
        WHEN TOTAL_PAGES_EXPECTED <> TOTAL_PAGES_FETCHED THEN 'PAGE_MISMATCH'
        WHEN TOTAL_RECORDS_INFO <> TOTAL_RECORDS_FETCHED THEN 'RECORD_MISMATCH'
        ELSE 'OK'
    END AS INGEST_CHECK,
    ERROR_MESSAGE
FROM "SOC_PIPELINE"."INGEST_RUNS"
ORDER BY STARTED_AT_UTC DESC
LIMIT 25;

-- ============================================================================
-- 5) Slowest ingestion runs: finds API or write-path stalls.
-- ============================================================================
SELECT '05_SLOWEST_INGEST_RUNS' AS SECTION FROM DUMMY;

SELECT
    RUN_ID,
    STATUS,
    STARTED_AT_UTC,
    DURATION_SECONDS,
    TOTAL_RECORDS_FETCHED,
    ROUND(TOTAL_RECORDS_FETCHED / NULLIF(DURATION_SECONDS, 0), 2) AS RECORDS_PER_SECOND,
    TOTAL_PAGES_FETCHED,
    ROUND(DURATION_SECONDS / NULLIF(TOTAL_PAGES_FETCHED, 0), 2) AS SECONDS_PER_PAGE,
    ERROR_MESSAGE
FROM "SOC_PIPELINE"."INGEST_RUNS"
ORDER BY DURATION_SECONDS DESC
LIMIT 20;

-- ============================================================================
-- 6) Run health summary: failure rate, throughput, and page mismatch count.
-- ============================================================================
SELECT '06_INGEST_HEALTH_SUMMARY' AS SECTION FROM DUMMY;

SELECT
    COUNT(*) AS RUNS,
    SUM(CASE WHEN STATUS <> 'success' THEN 1 ELSE 0 END) AS FAILED_RUNS,
    SUM(CASE WHEN TOTAL_PAGES_EXPECTED <> TOTAL_PAGES_FETCHED THEN 1 ELSE 0 END) AS PAGE_MISMATCH_RUNS,
    SUM(CASE WHEN TOTAL_RECORDS_INFO <> TOTAL_RECORDS_FETCHED THEN 1 ELSE 0 END) AS RECORD_MISMATCH_RUNS,
    ROUND(AVG(DURATION_SECONDS), 2) AS AVG_DURATION_SECONDS,
    ROUND(MAX(DURATION_SECONDS), 2) AS MAX_DURATION_SECONDS,
    ROUND(AVG(TOTAL_RECORDS_FETCHED / NULLIF(DURATION_SECONDS, 0)), 2) AS AVG_RECORDS_PER_SECOND
FROM "SOC_PIPELINE"."INGEST_RUNS";

-- ============================================================================
-- 7) Data freshness: latest timestamps per major table.
-- ============================================================================
SELECT '07_DATA_FRESHNESS' AS SECTION FROM DUMMY;

SELECT 'RAW_LOGS.LOG_TS' AS SIGNAL, MAX(LOG_TS) AS LATEST_VALUE
FROM "SOC_PIPELINE"."RAW_LOGS"
UNION ALL
SELECT 'RAW_LOGS.INGESTED_AT', MAX(INGESTED_AT)
FROM "SOC_PIPELINE"."RAW_LOGS"
UNION ALL
SELECT 'INGEST_RUNS.STARTED_AT_UTC', MAX(STARTED_AT_UTC)
FROM "SOC_PIPELINE"."INGEST_RUNS"
UNION ALL
SELECT 'WINDOW_METRICS.SAVED_AT_UTC', MAX(SAVED_AT_UTC)
FROM "SOC_PIPELINE"."WINDOW_METRICS"
UNION ALL
SELECT 'WINDOW_FEATURES.SAVED_AT_UTC', MAX(SAVED_AT_UTC)
FROM "SOC_PIPELINE"."WINDOW_FEATURES"
UNION ALL
SELECT 'ALERTS_EVENTS.DETECTED_AT_UTC', MAX(DETECTED_AT_UTC)
FROM "SOC_PIPELINE"."ALERTS_EVENTS";

-- ============================================================================
-- 8) Raw log volume by hour: detects traffic spikes and ingestion gaps.
-- Uses string hour bucketing because LOG_TS is stored as NVARCHAR.
-- ============================================================================
SELECT '08_RAW_LOG_VOLUME_BY_HOUR' AS SECTION FROM DUMMY;

SELECT
    SUBSTRING(COALESCE(LOG_TS, INGESTED_AT), 1, 13) || ':00' AS HOUR_UTC,
    COUNT(*) AS RAW_LOGS,
    SUM(CASE WHEN IS_SYSTEM_LOG = 1 THEN 1 ELSE 0 END) AS SYSTEM_LOGS,
    SUM(CASE WHEN IS_LLM_LOG = 1 THEN 1 ELSE 0 END) AS LLM_LOGS
FROM "SOC_PIPELINE"."RAW_LOGS"
WHERE COALESCE(LOG_TS, INGESTED_AT) IS NOT NULL
GROUP BY SUBSTRING(COALESCE(LOG_TS, INGESTED_AT), 1, 13)
ORDER BY HOUR_UTC DESC
LIMIT 48;

-- ============================================================================
-- 9) Raw log data quality: bad/missing timestamps and large payloads.
-- ============================================================================
SELECT '09_RAW_LOG_DATA_QUALITY' AS SECTION FROM DUMMY;

SELECT
    COUNT(*) AS RAW_LOGS,
    SUM(CASE WHEN LOG_TS IS NULL OR LOG_TS = '' THEN 1 ELSE 0 END) AS MISSING_LOG_TS,
    SUM(CASE WHEN INGESTED_AT IS NULL OR INGESTED_AT = '' THEN 1 ELSE 0 END) AS MISSING_INGESTED_AT,
    ROUND(AVG(LENGTH(PAYLOAD)), 2) AS AVG_PAYLOAD_CHARS,
    MAX(LENGTH(PAYLOAD)) AS MAX_PAYLOAD_CHARS
FROM "SOC_PIPELINE"."RAW_LOGS";

-- ============================================================================
-- 10) Biggest payloads: large rows can slow scans and dashboard reads.
-- ============================================================================
SELECT '10_LARGEST_RAW_PAYLOADS' AS SECTION FROM DUMMY;

SELECT
    LOG_ID,
    LOG_TS,
    INGESTED_AT,
    LENGTH(PAYLOAD) AS PAYLOAD_CHARS
FROM "SOC_PIPELINE"."RAW_LOGS"
ORDER BY LENGTH(PAYLOAD) DESC
LIMIT 20;

-- ============================================================================
-- 11) Heaviest windows: high total records, scores, or detections.
-- ============================================================================
SELECT '11_HEAVIEST_WINDOWS' AS SECTION FROM DUMMY;

SELECT
    WINDOW_KEY,
    RUN_ID,
    WINDOW_START,
    WINDOW_END,
    TOTAL_RECORDS,
    THREAT_SCORE,
    DETECTION_COUNT,
    ATTACK_PREDICTED,
    IS_ANOMALY,
    ANOMALY_SCORE,
    SAVED_AT_UTC
FROM "SOC_PIPELINE"."WINDOW_METRICS"
ORDER BY TOTAL_RECORDS DESC, THREAT_SCORE DESC
LIMIT 25;

-- ============================================================================
-- 12) Window processing lag: raw windows with no metrics yet.
-- ============================================================================
SELECT '12_RAW_WINDOWS_MISSING_METRICS' AS SECTION FROM DUMMY;

SELECT
    RAW_WINDOW.HOUR_UTC,
    RAW_WINDOW.RAW_LOGS
FROM (
    SELECT
        SUBSTRING(COALESCE(LOG_TS, INGESTED_AT), 1, 13) || ':00' AS HOUR_UTC,
        COUNT(*) AS RAW_LOGS
    FROM "SOC_PIPELINE"."RAW_LOGS"
    WHERE COALESCE(LOG_TS, INGESTED_AT) IS NOT NULL
    GROUP BY SUBSTRING(COALESCE(LOG_TS, INGESTED_AT), 1, 13)
) RAW_WINDOW
LEFT JOIN (
    SELECT
        SUBSTRING(COALESCE(WINDOW_START, SAVED_AT_UTC), 1, 13) || ':00' AS HOUR_UTC,
        COUNT(*) AS METRIC_WINDOWS
    FROM "SOC_PIPELINE"."WINDOW_METRICS"
    WHERE COALESCE(WINDOW_START, SAVED_AT_UTC) IS NOT NULL
    GROUP BY SUBSTRING(COALESCE(WINDOW_START, SAVED_AT_UTC), 1, 13)
) METRIC_WINDOW
    ON RAW_WINDOW.HOUR_UTC = METRIC_WINDOW.HOUR_UTC
WHERE COALESCE(METRIC_WINDOW.METRIC_WINDOWS, 0) = 0
ORDER BY RAW_WINDOW.HOUR_UTC DESC
LIMIT 48;

-- ============================================================================
-- 13) Feature coverage: model training input compared with metrics.
-- ============================================================================
SELECT '13_FEATURE_COVERAGE_BY_RUN' AS SECTION FROM DUMMY;

SELECT
    M.RUN_ID,
    COUNT(M.WINDOW_KEY) AS METRIC_WINDOWS,
    COUNT(F.WINDOW_KEY) AS FEATURE_WINDOWS,
    COUNT(M.WINDOW_KEY) - COUNT(F.WINDOW_KEY) AS MISSING_FEATURE_WINDOWS,
    ROUND(100 * COUNT(F.WINDOW_KEY) / NULLIF(COUNT(M.WINDOW_KEY), 0), 2) AS FEATURE_COVERAGE_PCT
FROM "SOC_PIPELINE"."WINDOW_METRICS" M
LEFT JOIN "SOC_PIPELINE"."WINDOW_FEATURES" F
    ON M.WINDOW_KEY = F.WINDOW_KEY
GROUP BY M.RUN_ID
ORDER BY M.RUN_ID DESC
LIMIT 50;

-- ============================================================================
-- 14) Alerts by type/severity: shows noisy rules and alert concentration.
-- ============================================================================
SELECT '14_ALERT_DISTRIBUTION' AS SECTION FROM DUMMY;

SELECT
    ALERT_TYPE,
    SEVERITY,
    COUNT(*) AS ALERTS,
    MIN(DETECTED_AT_UTC) AS FIRST_DETECTED_AT_UTC,
    MAX(DETECTED_AT_UTC) AS LAST_DETECTED_AT_UTC
FROM "SOC_PIPELINE"."ALERTS_EVENTS"
GROUP BY ALERT_TYPE, SEVERITY
ORDER BY ALERTS DESC, LAST_DETECTED_AT_UTC DESC;

-- ============================================================================
-- 15) Model run duration and prediction volume.
-- ============================================================================
SELECT '15_MODEL_RUNS_AND_PREDICTIONS' AS SECTION FROM DUMMY;

SELECT
    MR.RUN_ID,
    MR.ALGORITHM,
    MR.STATUS,
    MR.TRAINING_ROW_COUNT,
    MR.CONTAMINATION,
    MR.STARTED_AT_UTC,
    MR.COMPLETED_AT_UTC,
    COUNT(MP.PREDICTION_ID) AS PREDICTIONS,
    AVG(MP.SCORE) AS AVG_SCORE,
    AVG(MP.CONFIDENCE) AS AVG_CONFIDENCE
FROM "SOC_PIPELINE"."MODEL_RUNS" MR
LEFT JOIN "SOC_PIPELINE"."MODEL_PREDICTIONS" MP
    ON MR.RUN_ID = MP.RUN_ID
GROUP BY
    MR.RUN_ID,
    MR.ALGORITHM,
    MR.STATUS,
    MR.TRAINING_ROW_COUNT,
    MR.CONTAMINATION,
    MR.STARTED_AT_UTC,
    MR.COMPLETED_AT_UTC
ORDER BY MR.STARTED_AT_UTC DESC
LIMIT 25;

-- ============================================================================
-- 16) Expensive HANA statements touching this app schema.
-- Requires expensive statement tracing to be enabled by the HANA tenant/admin.
-- ============================================================================
SELECT '16_EXPENSIVE_STATEMENTS_FOR_SCHEMA' AS SECTION FROM DUMMY;

SELECT
    START_TIME,
    ROUND(DURATION_MICROSEC / 1000000, 3) AS DURATION_SECONDS,
    DB_USER,
    OPERATION,
    RECORDS,
    SUBSTRING(STATEMENT_STRING, 1, 1000) AS STATEMENT_SAMPLE
FROM SYS.M_EXPENSIVE_STATEMENTS
WHERE UPPER(STATEMENT_STRING) LIKE '%SOC_PIPELINE%'
ORDER BY START_TIME DESC
LIMIT 50;

-- ============================================================================
-- 17) Delta storage pressure: high delta memory can make writes/scans slower.
-- Consider a delta merge if a table has large delta memory and heavy writes.
-- ============================================================================
SELECT '17_DELTA_STORAGE_PRESSURE' AS SECTION FROM DUMMY;

SELECT
    TABLE_NAME,
    RECORD_COUNT,
    ROUND(MEMORY_SIZE_IN_TOTAL / 1024 / 1024, 2) AS TOTAL_MB,
    ROUND(MEMORY_SIZE_IN_DELTA / 1024 / 1024, 2) AS DELTA_MB,
    ROUND(100 * MEMORY_SIZE_IN_DELTA / NULLIF(MEMORY_SIZE_IN_TOTAL, 0), 2) AS DELTA_MEMORY_PCT
FROM SYS.M_CS_TABLES
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
ORDER BY MEMORY_SIZE_IN_DELTA DESC;

-- ============================================================================
-- 18) Current table locks: checks whether writes/reads are blocked.
-- ============================================================================
SELECT '18_LOCKS_ON_APP_OBJECTS' AS SECTION FROM DUMMY;

SELECT
    HOST,
    PORT,
    CONNECTION_ID,
    TRANSACTION_ID,
    LOCK_MODE,
    LOCK_STATUS,
    SCHEMA_NAME,
    TABLE_NAME,
    OBJECT_NAME
FROM SYS.M_TABLE_LOCKS
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
ORDER BY TABLE_NAME, LOCK_STATUS;
