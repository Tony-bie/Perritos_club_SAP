# Migraciones HANA

Ejecuta estas migraciones después de `sql/hana_setup.sql`.

## Orden de Ejecución

1. `sql/hana_setup.sql` — esquema base (`RAW_LOGS`, `WINDOW_METRICS`, `ALERTS_EVENTS`, etc.).
2. `001_analytics_extension_tables.sql` — tablas analíticas adicionales.
3. `002_analytics_extension_views.sql` — vistas para tablero y análisis.
4. `003_optimizations.sql` — índices secundarios.
5. `004_retention.sql` — tabla de auditoría y procedimiento de limpieza.
6. `999_validate_block_b.sql` — validación de objetos creados.

También puedes usar:

```bash
python tools/run_hana_migrations.py
```

## Por Qué Están Separadas

SAP HANA puede fallar al compilar vistas en el mismo lote donde se crean o modifican tablas/columnas. Separar scripts reduce errores semánticos y facilita validar cada bloque.

## Validaciones Útiles

```sql
-- Objetos por tipo
SELECT OBJECT_TYPE, COUNT(*)
FROM SYS.OBJECTS
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
GROUP BY OBJECT_TYPE;

-- Índices creados
SELECT INDEX_NAME, TABLE_NAME
FROM SYS.INDEXES
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
ORDER BY TABLE_NAME, INDEX_NAME;

-- Procedimiento de limpieza
SELECT PROCEDURE_NAME
FROM SYS.PROCEDURES
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
  AND PROCEDURE_NAME = 'sp_cleanup_old_data';

-- Auditoría
SELECT COUNT(*)
FROM "SOC_PIPELINE"."AUDIT_LOG";
```

## Problemas Comunes

### Fallan vistas de `002_analytics_extension_views.sql`

Si aparecen errores por tablas no resueltas, vuelve a ejecutar:

1. `001_analytics_extension_tables.sql`
2. `002_analytics_extension_views.sql`

### Falla `004_retention.sql`

Revisa que los scripts previos hayan terminado bien. Si `AUDIT_LOG` quedó en estado parcial, puedes eliminarla y repetir:

```sql
DROP TABLE "SOC_PIPELINE"."AUDIT_LOG" CASCADE;
```

Luego ejecuta otra vez `004_retention.sql`.

## Reversión Parcial de Bloque B

Si necesitas deshacer optimizaciones sin borrar datos:

```sql
DROP INDEX "SOC_PIPELINE"."RAW_LOGS_TIMESTAMP_SEVERITY_HOST_IDX";
DROP INDEX "SOC_PIPELINE"."RAW_LOGS_SERVICE_TIME_IDX";
DROP INDEX "SOC_PIPELINE"."WINDOW_METRICS_RUN_WINDOW_IDX";
DROP INDEX "SOC_PIPELINE"."ALERTS_EVENTS_TIME_SEVERITY_IDX";
DROP PROCEDURE "SOC_PIPELINE"."sp_cleanup_old_data";
```

`AUDIT_LOG` puede conservarse como rastro de auditoría.
