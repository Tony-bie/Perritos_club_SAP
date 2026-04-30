# HANA Migrations

## Block A execution order (Tablas + Vistas)

1. Run `001_analytics_extension_tables.sql`
2. Run `002_analytics_extension_views.sql`

## Block B execution order (Optimizaciones + Retención)

3. Run `003_optimizations.sql` — Índices secundarios
4. Run `004_retention.sql` — Stored procedures de limpieza

## Why split the scripts?

SAP HANA can surface semantic errors when views are compiled in the same batch as table/column evolution. Splitting the scripts keeps the parser stable and makes each step easier to validate.

## Base schema dependency

Apply these scripts after `sql/hana_setup.sql`.

## Complete Execution Sequence

```
1. hana_setup.sql (base schema: RAW_LOGS, WINDOW_METRICS, DETECTIONS, etc.)
2. 001_analytics_extension_tables.sql (add MODEL_RUNS, MODEL_PREDICTIONS, etc.)
3. 002_analytics_extension_views.sql (create VW_LATEST_ALERTS, VW_RISK_TIMELINE, etc.)
4. 003_optimizations.sql (create indices on critical columns — SQL pure, no procedures)
5. 004_retention.sql (create AUDIT_LOG table + sp_cleanup_old_data procedure)
6. 999_validate_block_b.sql (validate that all Bloque B objects were created correctly)
```

## Troubleshooting

### Bloque A Issues

If `002_analytics_extension_views.sql` fails with unresolved table errors (for example `MODEL_RUNS` or `MODEL_PREDICTIONS`), rerun step 1 and then step 2:

1. `001_analytics_extension_tables.sql`
2. `002_analytics_extension_views.sql`

### Bloque B Issues

If `004_retention.sql` fails with procedure creation errors:
- Verify `001` and `002` completed successfully
- Check that `AUDIT_LOG` table doesn't exist (script recreates it)
- If needed, manually drop: `DROP TABLE "SOC_PIPELINE"."AUDIT_LOG" CASCADE;`
- Rerun `004_retention.sql`

## Validation Queries

```sql
-- Verify Block A objects
SELECT OBJECT_TYPE, COUNT(*) FROM SYS.OBJECTS 
WHERE SCHEMA_NAME = 'SOC_PIPELINE' 
GROUP BY OBJECT_TYPE;

-- Verify indices created in Block B
SELECT INDEX_NAME, TABLE_NAME FROM SYS.INDEXES 
WHERE SCHEMA_NAME = 'SOC_PIPELINE' 
ORDER BY TABLE_NAME, INDEX_NAME;

-- Verify cleanup procedure exists
SELECT PROCEDURE_NAME FROM SYS.PROCEDURES 
WHERE SCHEMA_NAME = 'SOC_PIPELINE' 
AND PROCEDURE_NAME = 'sp_cleanup_old_data';

-- Verify AUDIT_LOG table
SELECT COUNT(*) FROM "SOC_PIPELINE"."AUDIT_LOG";
```

## Rollback Strategy

If you need to rollback Bloque B (keep data intact):

```sql
-- Drop indices (safe, no data loss)
DROP INDEX "SOC_PIPELINE"."RAW_LOGS_TIMESTAMP_SEVERITY_HOST_IDX";
DROP INDEX "SOC_PIPELINE"."RAW_LOGS_SERVICE_TIME_IDX";
DROP INDEX "SOC_PIPELINE"."WINDOW_METRICS_RUN_WINDOW_IDX";
DROP INDEX "SOC_PIPELINE"."ALERTS_EVENTS_TIME_SEVERITY_IDX";

-- Drop procedure (safe, AUDIT_LOG remains for audit trail)
DROP PROCEDURE "SOC_PIPELINE"."sp_cleanup_old_data";
```

## Documentation

- See [docs/block_b.md](../docs/block_b.md) for detailed implementation guide and performance expectations.
