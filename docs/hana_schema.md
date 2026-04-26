# SAP HANA Schema - Block A

This document describes the additive schema extension used for the analytics layer.

## Existing base objects

The base bootstrap already creates the following objects:

- `RAW_LOGS`
- `WINDOW_METRICS`
- `DETECTIONS`
- `TRAINING_LABELS`
- `MODEL_RUNS`
- `MODEL_SCORES`

## Added analytics objects

The Block A migration adds these objects:

- `MODEL_PREDICTIONS`
- `FEATURE_DEFINITIONS`
- `ALERT_FEEDBACK`
- `ALERTS_EVENTS`
- `VW_LATEST_ALERTS`
- `VW_RISK_TIMELINE`
- `VW_MODEL_PERFORMANCE`
- `VW_ALERT_SUMMARY`

## Execution order

Run the migration files in this order after `sql/hana_setup.sql`:

1. `sql/migrations/001_analytics_extension_tables.sql`
2. `sql/migrations/002_analytics_extension_views.sql`

## View intent

### `VW_LATEST_ALERTS`
Latest 100 alerts ordered by detection time.

### `VW_RISK_TIMELINE`
Window-level risk timeline for dashboards.

### `VW_MODEL_PERFORMANCE`
Aggregated model performance by `RUN_ID` and model metadata.

### `VW_ALERT_SUMMARY`
Alert counts grouped by alert type and severity.

## Validation queries

```sql
SET SCHEMA SOC_PIPELINE;

SELECT TABLE_NAME
FROM SYS.TABLES
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
  AND TABLE_NAME IN (
    'RAW_LOGS',
    'WINDOW_METRICS',
    'DETECTIONS',
    'TRAINING_LABELS',
    'MODEL_RUNS',
    'MODEL_SCORES',
    'MODEL_PREDICTIONS',
    'FEATURE_DEFINITIONS',
    'ALERT_FEEDBACK',
    'ALERTS_EVENTS'
  );

SELECT VIEW_NAME
FROM SYS.VIEWS
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
  AND VIEW_NAME IN (
    'VW_LATEST_ALERTS',
    'VW_RISK_TIMELINE',
    'VW_MODEL_PERFORMANCE',
    'VW_ALERT_SUMMARY'
  );
```
