# Bloque B: Storage Optimization & Retención

## Objetivo
Optimizar el rendimiento de lectura/escritura en HANA mediante:
- Batch upserts (inserción en lotes vía `executemany()`)
- Índices secundarios para filtrados comunes
- Particionado por fecha para acelerar scans y retención
- Política de retención automática (sp_cleanup_old_data)
- Agregaciones eficientes mediante vistas materializadas

## Archivos Generados

### SQL Migrations
1. **`003_optimizations.sql`** — Índices secundarios en:
   - `RAW_LOGS(EVENT_TIME, SEVERITY, SOURCE_HOST)`
   - `RAW_LOGS(SERVICE_NAME, EVENT_TIME)`
   - `WINDOW_METRICS(RUN_ID, WINDOW_START)`
   - `ALERTS_EVENTS(EVENT_TIME, SEVERITY, RUN_ID)`
   
2. **`004_retention.sql`** — Stored procedures:
   - `sp_cleanup_old_data(retention_days)` — Elimina datos antiguos en cascada
   - `AUDIT_LOG` — Tabla para registrar operaciones
   - Ejemplos de scheduling (HANA job, Cloud Foundry endpoint)

### Python Backend
- **`backend/core/config.py`** — Nuevos parámetros:
  - `BATCH_SIZE` (default 1000) — Tamaño de lote para bulk upserts
  - `RETENTION_DAYS` (default 90) — Días a mantener históricamente
  - `CLEANUP_SCHEDULE_ENABLED` (default true) — Habilitar cleanup automático
  - `CLEANUP_SCHEDULE_HOUR` (default 2) — Hora para ejecutar cleanup

- **`backend/storage/backends/store.py`** — Métodos a añadir:
  - `bulk_upsert_window_metrics(records, batch_size)` — Inserta por lotes usando `cursor.executemany()`
  - `bulk_upsert_raw_logs(records, batch_size)` — Similar para RAW_LOGS
  - `call_cleanup_procedure(retention_days)` — Llamar a `sp_cleanup_old_data()`

- **`backend/api/admin/cleanup.py`** — Endpoint para cleanup manual:
  - `POST /api/admin/cleanup` — Trigger cleanup on-demand (requiere API key)
  - Parámetros: `{ "retention_days": 90 }`
  - Respuesta: `{ "status": "cleaned", "rows_deleted": 12345 }`

### Documentación
- **`docs/block_b.md`** (este archivo) — Guía de implementación y operación

## Configuración en `.env`

```properties
# Bloque B: Optimization & Retention
BATCH_SIZE=1000
RETENTION_DAYS=90
CLEANUP_SCHEDULE_ENABLED=true
CLEANUP_SCHEDULE_HOUR=2
```

## Implementación Paso a Paso

### Paso 1: Aplicar migraciones SQL

```bash
# Conectar a HANA (ej. via hdbsql, HANA Studio, o script Python)
# Ejecutar en orden (copia y pega cada script):
1. sql/migrations/001_analytics_extension_tables.sql
2. sql/migrations/002_analytics_extension_views.sql
3. sql/migrations/003_optimizations.sql  # <-- Índices (SQL puro, ejecutable directo)
4. sql/migrations/004_retention.sql      # <-- Tabla AUDIT_LOG + procedure (SQL + SQLScript)
```

**Cambios en Scripts (Bloque B reescrito para HANA puro):**
- `003_optimizations.sql`: Ahora contiene solo `CREATE INDEX` statements (SQL puro). Sin procedimientos complejos, sin EXEC SQL. Puedes ejecutar directamente.
- `004_retention.sql`: Separado en dos partes:
  1. Crear tabla `AUDIT_LOG` (SQL puro)
  2. Crear procedure `sp_cleanup_old_data(retention_days)` (SQL + SQLScript dentro del CREATE PROCEDURE)
  
  Esto es la sintaxis correcta de HANA: la lógica SQLScript va DENTRO del CREATE PROCEDURE, no en un bloque DO anónimo.

**Validación:**
```sql
-- Ejecuta este script para validar que todo se creó correctamente:
sql/migrations/999_validate_block_b.sql

-- Esperado:
-- - 4 índices creados (RAW_LOGS_TIMESTAMP_SEVERITY_HOST_IDX, RAW_LOGS_SERVICE_TIME_IDX, etc.)
-- - Tabla AUDIT_LOG existe y vacía
-- - Procedure sp_cleanup_old_data existe
-- - Dry run de procedure completa sin errores (cero filas borradas porque retention_days=999)
```

### Paso 2: Actualizar Backend (`store.py`)

Añadir métodos de bulk upsert (pseudocódigo; implementación real incluida en PR):

```python
# backend/storage/backends/store.py

class HanaStore:
    def bulk_upsert_window_metrics(self, records: list[dict], batch_size: int = 1000) -> int:
        """
        Insertar/actualizar métricas en lotes para reducir overhead de transacciones.
        Usa UPSERT (MERGE en HANA) por lote.
        Retorna número total de filas procesadas.
        """
        total_rows = 0
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            # Construir sentencia MERGE/UPSERT
            # Ejecutar con executemany() si es posible
            # Commit por lote
            total_rows += len(batch)
        return total_rows
    
    def call_cleanup_procedure(self, retention_days: int = 90) -> dict:
        """
        Invocar sp_cleanup_old_data(retention_days).
        Retorna { "status": "cleaned", "rows_deleted": N }
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(f'CALL "SOC_PIPELINE"."sp_cleanup_old_data"(retention_days => {retention_days})')
            # Leer resultados de AUDIT_LOG si es necesario
            result = {"status": "cleaned", "rows_deleted": 0}
            return result
```

### Paso 3: Endpoint Admin para Cleanup (`backend/api/admin/cleanup.py`)

Crear endpoint protegido para trigger cleanup on-demand:

```python
# backend/api/admin/cleanup.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin", tags=["admin"])

class CleanupRequest(BaseModel):
    retention_days: int = 90
    api_key: str  # o usar auth header

@router.post("/cleanup")
async def trigger_cleanup(req: CleanupRequest, store: HanaStore = Depends(...)):
    """
    Trigger on-demand data cleanup.
    Requiere valid API key o autenticación.
    Parámetros:
      - retention_days: cuántos días mantener (default 90)
      - api_key: clave secreta
    Respuesta:
      { "status": "cleaned", "rows_deleted": 12345 }
    """
    # Validar API key
    if not validate_api_key(req.api_key):
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    # Ejecutar cleanup
    result = store.call_cleanup_procedure(retention_days=req.retention_days)
    return result
```

Montar en app:
```python
# main.py / application.py
from backend.api.admin.cleanup import router as admin_router
app.include_router(admin_router)
```

### Paso 4: Scheduler Externo (Recomendado para CF)

Para Cloud Foundry, no uses HANA job; en su lugar, configura un external scheduler:

**Opción A: Cloud Foundry Scheduler (ej. SAP Cloud Platform)**
```bash
# Crear job que llame a endpoint
cf create-service scheduler standard cleanup-scheduler
cf create-service-key cleanup-scheduler cleanup-key
cf bind-service Perritos-backend cleanup-scheduler

# O usar una CF Route + external cron (GitHub Actions, Azure Scheduler, etc.)
```

**Opción B: GitHub Actions (recomendado para CI/CD)**
```yaml
# .github/workflows/cleanup.yml
name: Cleanup Old Data
on:
  schedule:
    - cron: "0 2 * * *"  # 02:00 AM UTC daily
jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger cleanup endpoint
        run: |
          curl -X POST https://perritos-backend.cfapps.*.hana.ondemand.com/api/admin/cleanup \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer ${{ secrets.CLEANUP_API_KEY }}" \
            -d '{"retention_days": 90}'
```

## Performance Esperado

### Antes (sin optimizaciones):
- INSERT de 10K rows: ~5-10s (sin índices, sin batch)
- SELECT de últimas 100 alertas: ~2-3s (sin índice en EVENT_TIME)
- Scan de 6 meses: O(N) sin particionado

### Después (con Bloque B):
- INSERT de 10K rows en 1000-row batches: ~1-2s
- SELECT últimas 100 alertas: <100ms (con índice EVENT_TIME)
- Scan de 6 meses: O(log N) con particionado por fecha
- Cleanup automática: 30-60min/noche, 0 impacto en consultas online

## Tests & Validación

### Test 1: Bulk Upsert
```bash
python -m pytest tests/test_bulk_upsert.py
# Verifica:
#   - Inserta 10K rows en 10 batches de 1K
#   - Mide tiempo/throughput
#   - Valida integridad (no duplicados)
```

### Test 2: Cleanup Procedure
```bash
# Inserta datos "antiguos" (timestamp < TODAY - 90 days)
# Llama sp_cleanup_old_data(90)
# Valida que filas antiguas se eliminaron
python -m pytest tests/test_cleanup.py
```

### Test 3: Index Effectiveness
```bash
# Compara EXPLAIN PLAN antes/después de índices
# Verifica que Estimated cost < 0.1 de antes
python tools/hana_explain_plan.py
```

## Monitoreo & Operación

### Queries Útiles para Monitoreo

```sql
-- Ver audit log de cleanup
SELECT * FROM "SOC_PIPELINE"."AUDIT_LOG" ORDER BY TIMESTAMP DESC LIMIT 100;

-- Ver tamaño de tablas
SELECT TABLE_NAME, TOTAL_SIZE/1024/1024 AS SIZE_MB 
FROM SYS.M_TABLES 
WHERE SCHEMA_NAME = 'SOC_PIPELINE'
ORDER BY TOTAL_SIZE DESC;

-- Ver estadísticas de índices (hits, I/O)
SELECT INDEX_NAME, HOST, READ_COUNT, MEMORY_USED_MB 
FROM SYS.M_INDEX_STATISTICS 
WHERE SCHEMA_NAME = 'SOC_PIPELINE';

-- Ver ejecuciones de procedure
SELECT * FROM SYS.PROCEDURE_EXECUTION_LOG 
WHERE PROCEDURE_NAME = 'sp_cleanup_old_data' 
ORDER BY TIMESTAMP DESC LIMIT 50;
```

### Alertas Recomendadas

- **Cleanup falla**: Monitorear `AUDIT_LOG` para errores
- **Disco lleno**: Si `TOTAL_SIZE` de tablas > 80% capacity
- **Índice no utilizado**: Si `READ_COUNT = 0` después de 7 días

## Problemas Comunes & Soluciones

### Problema: Cleanup tarda > 1 hora
**Causa**: Muchas filas, locks contenciosos
**Solución**: 
- Reducir `batch_size` en fase DELETE (ej. `batch_size=10000`)
- Ejecutar cleanup en ventana de bajo tráfico
- Particionar tabla por fecha (future enhancement)

### Problema: Índices no se usan
**Causa**: Plan optimizer elige full table scan
**Solución**:
```sql
-- Recolectar estadísticas
ANALYZE TABLE "SOC_PIPELINE"."WINDOW_METRICS" COMPUTE STATISTICS;
-- Invalidar plan cache
SET SESSION SQL_PLAN_CACHE=OFF;
```

### Problema: INSERT lento a pesar de batching
**Causa**: HANA comprime columnas; overhead por batch
**Solución**:
- Aumentar `batch_size` a 5000 o 10000
- Usar `MERGE` en lugar de INSERT + UPDATE

## Próximos Pasos (Bloque C)

1. Endpoints SAC/Streamlit (GET /alerts/recent, /metrics/windows, etc.)
2. Validación de datos + schemas Pydantic
3. Documentación OpenAPI/Swagger
4. Tests de integración E2E

---

**Última actualización**: April 2026  
**Estado**: Fase 2 (Implementación en progreso)  
**Responsables**: Backend Team  
**Branch**: `backend-fase-2`
