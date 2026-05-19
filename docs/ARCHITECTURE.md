# ARQUITECTURA — Live Security Operation Center Defense

**Última actualización**: mayo de 2026
**Audiencia**: técnica y no técnica
**Objetivo**: entender qué hace el sistema, por qué existe cada componente y cómo fluyen los datos.

---

## El Problema

SAP SOC puede generar miles o millones de eventos operativos, de seguridad y de LLM. Revisarlos manualmente no escala. El sistema busca:

- Detectar anomalías y correlaciones de seguridad automáticamente.
- Separar degradación operativa de posibles ataques.
- Mantener historial consultable para tableros y análisis.
- Enviar alertas cuando hay señales suficientemente fuertes.
- Seguir funcionando aunque HANA falle temporalmente, usando SQLite como respaldo.

**Nuestra solución**: ingesta de registros + ventanas históricas + reglas de correlación + línea base estadística + modelo HANA ML + alertas + API/tablero/chatbot.

---

## Flujo Completo

```text
SAP SOC API
  |
  | 1. Descarga registros paginados (/info + /logs/current)
  v
Normalización
  |
  | Clasifica LLM vs sistema, agrega ingested_at, conserva payload
  v
RAW_LOGS
  |
  | Agrupa por timestamp real en ventanas de 30 min
  v
WINDOW_METRICS
  |
  | Línea base histórica desde WINDOW_METRICS
  | Modelo HANA ML desde WINDOW_FEATURES
  | Reglas actuales de seguridad/LLM/HTTP
  v
Evaluación de Riesgo
  |
  | threat_score, risk_level, anomaly_reason, attack_predicted
  v
ALERTS_EVENTS + API + Telegram/Chatbot
```

Punto importante: **historial insuficiente no apaga todas las alertas**. Solo limita la comparación contra comportamiento normal histórico. Las reglas de correlación fuertes siguen funcionando.

---

## Componentes

### 1. Servicio de ingesta (`backend/services/ingestion/`)

**Qué hace**

- Consulta SAP SOC API.
- Descarga páginas de registros.
- Normaliza cada registro.
- Guarda registros crudos en `RAW_LOGS`.
- Construye ventanas de 30 minutos desde timestamps reales (`@timestamp`, `event_time`, `timestamp`, etc.).

**Por qué**

La detección opera por ventanas. Si varias ingestas traen registros de distintas horas o días, el sistema debe crear varias filas históricas, no sobrescribir una sola ventana.

**Archivos**

- `ingest.py`: orquesta la llamada a SAP SOC.
- `normalize.py`: clasifica registros LLM vs sistema.
- `features.py`: agrupa por ventanas y extrae features numéricas.

**Salida principal**

- `RAW_LOGS`: todos los registros crudos.
- `WINDOW_METRICS`: métricas agregadas por ventana.

---

### 2. Detección y riesgo (`backend/services/detection/`)

El sistema combina tres capas:

| Capa | Fuente | Sirve para |
|------|--------|------------|
| Reglas actuales | ventana actual | Detectar correlaciones fuertes aunque no haya historial |
| Novedad | ventana actual + ventanas recientes | Marcar valores nunca vistos antes |
| Línea base histórica | `WINDOW_METRICS` | Comparar contra comportamiento normal reciente |
| Modelo HANA ML | `WINDOW_FEATURES` | Puntaje ML cuando hay suficientes features limpias |

**Reglas actuales**

Pueden disparar alertas aún con historial insuficiente. Ejemplos:

- `SECURITY_ERROR_CORRELATION`
- `SECURITY_HTTP_FAILURE_CORRELATION`
- `SECURITY_SINGLE_IP_PRESSURE`
- `SECURITY_LLM_DISRUPTION_CORRELATION`

**Novedad**

Marca valores nunca vistos antes como `novel_activity`. Aplica a tipos de log, servicios, códigos HTTP y modelos LLM observados en la ventana actual.

La novedad no predice ataque por sí sola. Significa: "esto apareció por primera vez o no estaba en las ventanas recientes", por lo que merece revisión aunque el modelo histórico aún esté en calibración.

**Línea base histórica**

Usa `WINDOW_METRICS`, no `WINDOW_FEATURES`. Esto es intencional: la línea base necesita ver el historial operativo completo, incluso ventanas con degradación LLM o sistema.

**Modelo HANA ML**

Usa `WINDOW_FEATURES`, que excluye algunas ventanas claramente anómalas o incompletas para no entrenar el modelo con ruido como si fuera normal.

**Archivos**

- `historical_baseline.py`: z-score robusto contra historial.
- `novelty.py`: primeros valores observados contra ventanas recientes.
- `model.py`: scoring con HANA ML/PAL cuando hay HANA disponible.
- `detect.py`: combina línea base, modelo y reglas.
- `alert.py`: formatea eventos y decide notificaciones.

---

## Qué Significa "Historial en Calibración"

Cuando `/history/status` muestra historial/modelo en `warming_up`, significa:

- La detección está activa.
- Las reglas actuales siguen evaluando cada ventana ingerida.
- La línea base todavía está calibrándose con ventanas en `WINDOW_METRICS`.
- El modelo ML puede estar calibrándose con filas limpias en `WINDOW_FEATURES`.

Ejemplo:

```json
{
  "detection_active": true,
  "training_required_for_detection": false,
  "baseline_signal_status": "warming_up",
  "historical_rows": 3,
  "historical_recommended_rows": 20,
  "historical_rows_to_calibration": 17,
  "historical_source_table": "window_metrics",
  "model_rows": 11,
  "model_source_table": "window_features"
}
```

Interpretación:

- `historical_rows`: ventanas disponibles para comparar comportamiento normal.
- `model_rows`: ventanas limpias disponibles para ML.
- `*_rows_to_calibration` no es una activación pendiente; es una meta recomendada para mejorar baseline/ML.
- Si `historical_rows` es bajo pero hay `SECURITY_ERROR_CORRELATION`, el sistema sí vio una correlación fuerte; solo no puede afirmar aún que sea raro respecto a la línea base.

---

## Capa de almacenamiento (`backend/storage/backends/`)

**Backend primario**

- SAP HANA Cloud cuando `STORAGE_BACKEND=hana`.

**Fallback SQLite**

- SQLite local funciona como fallback/respaldo cuando HANA falla.
- Al recuperarse HANA, `ResilientStore` intenta sincronizar pendientes automáticamente.
- También existe una ruta manual para resincronización.

**Tablas**

| Tabla | Propósito | Notas |
|-------|-----------|-------|
| `RAW_LOGS` | Registros crudos normalizados | Fuente para reconstruir ventanas |
| `WINDOW_METRICS` | Ventanas agregadas y resumen de riesgo | Fuente de la línea base histórica |
| `WINDOW_FEATURES` | Features limpias para ML | Fuente del modelo |
| `ALERTS_EVENTS` | Alertas generadas | Usado por tablero/chatbot |
| `INGEST_RUNS` | Ciclos de ingesta | Auditoría operativa |

---

## API REST (`backend/api/http/application.py`)

### Estado y lectura

| Ruta | Método | Propósito |
|----------|--------|-----------|
| `/health` | GET | Estado del backend, proceso en segundo plano, almacenamiento y respaldo |
| `/health/sap` | GET | Verifica SAP SOC API |
| `/history/status` | GET | Estado de línea base y modelo |
| `/status/latest` | GET | Última ejecución y última ventana |
| `/alerts/recent?limit=50` | GET | Alertas recientes |
| `/metrics/windows?limit=50` | GET | Ventanas recientes |
| `/runs/recent?limit=10` | GET | Ejecuciones recientes |
| `/dashboard/summary?time_window_hours=24` | GET | Agregado para tablero |

### Operación y admin

| Ruta | Método | Propósito |
|----------|--------|-----------|
| `/run/ingestion` | POST | Ejecuta una ingesta manual |
| `/run/reprocess-windows` | POST | Recalcula riesgo de ventanas existentes |
| `/run/rebuild-windows-from-raw` | POST | Reconstruye `WINDOW_METRICS` desde `RAW_LOGS` |
| `/run/resync-fallback` | POST | Fuerza sincronización del fallback SQLite hacia HANA |
| `/api/admin/cleanup` | POST | Limpieza por retención |

Las rutas admin requieren token (`Authorization: Bearer ...` o `X-API-Key`).

---

## Chatbot / Telegram

El bot de Telegram vive en `backend/api/http/application.py` y usa `backend/services/chatbot/interpreter.py` para interpretar preguntas con LiteLLM. La idea no es que el modelo "adivine": el backend le entrega un contexto estructurado con resumen operativo e instantáneas equivalentes a estas rutas:

- `/health`
- `/history/status`
- `/status/latest`
- `/dashboard/summary`
- `/alerts/recent`
- `/metrics/windows`
- `/runs/recent`
- `/health/sap`

El prompt obliga al modelo a responder en español, usar solo ese contexto, mencionar la ruta que respalda la conclusión cuando sea útil y mantener foco operativo. La salida se marca como `Fuente: llm`.

Si `LLM_ENABLED=false`, falta `LLM_PROVIDER_MODEL`, LiteLLM no está instalado o el proveedor falla, el bot no se rompe: responde con un resumen local basado en el mismo contexto y marca `Fuente: fallback`.

Variables principales:

```text
TOKEN_BOT_TELEGRAM=...
CHAT_IDS=...
TELEGRAM_CHATBOT_ENABLED=true
LLM_ENABLED=true
LLM_PROVIDER_MODEL=groq/llama-3.1-8b-instant
LLM_API_KEY=...
LLM_BASE_URL=
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=400
```

`LLM_BASE_URL` es opcional y sirve para un proxy LiteLLM, gateway propio o endpoint local compatible. LiteLLM está incluido en `requirements.txt`.

---

## Ciclo de Vida de una Alerta

```text
1. Ingesta
   SAP SOC API -> normalización -> RAW_LOGS

2. Ventanas
   RAW_LOGS -> ventanas de 30 min -> WINDOW_METRICS

3. Detección
   Reglas actuales + línea base histórica + modelo HANA ML

4. Resumen de riesgo
   threat_score, risk_level, anomaly_reason, attack_predicted

5. Alertas
   ALERTS_EVENTS + posible Telegram + API/tablero

6. Retención
   limpieza automática/manual según configuración
```

---

## Decisiones de Diseño

### Por qué separar línea base y modelo

Antes, contar solo `WINDOW_FEATURES` podía hacer parecer que no había historial, porque esa tabla excluye ventanas anómalas para no contaminar el ML.

Ahora:

- `WINDOW_METRICS` alimenta la línea base histórica.
- `WINDOW_FEATURES` alimenta el modelo.

Esto evita que el sistema "esconda" semanas de datos solo porque fueron degradadas o anómalas.

### Por qué reconstruir desde RAW_LOGS

Si por un bug anterior varias ingestas pisaron el mismo `WINDOW_KEY`, todavía podemos recuperar historial si `RAW_LOGS` contiene timestamps reales.

Ruta:

```bash
curl -X POST "http://localhost:8000/run/rebuild-windows-from-raw?limit=0&persist=true" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

### Por qué SQLite como fallback/respaldo

Si HANA falla temporalmente:

- Las escrituras caen a SQLite.
- `/health` reporta pendientes.
- Cuando HANA vuelve, `ResilientStore` intenta sincronizar.
- También se puede forzar con `/run/resync-fallback`.

---

## Tecnologías

| Capa | Tecnología | Razón |
|-------|------------|-------|
| Entorno | Python | Ecosistema backend/ML |
| Web | FastAPI | API JSON, validación, OpenAPI |
| DB primaria | SAP HANA Cloud | Integración SAP, almacenamiento columnar |
| Fallback/local | SQLite | Resiliencia local/dev |
| ML | HANA ML/PAL | Scoring cerca de los datos en HANA |
| Bot | aiogram + LiteLLM | Telegram y respuestas interpretadas |
| Migraciones | SQL + scripts Python | Evolución controlada del esquema |

---

## Operación Recomendada

### Ver estado

```bash
curl http://localhost:8000/health
curl http://localhost:8000/history/status
curl http://localhost:8000/status/latest
```

### Ejecutar ingesta manual

```bash
curl -X POST http://localhost:8000/run/ingestion
```

### Recalcular ventanas existentes

```bash
curl -X POST "http://localhost:8000/run/reprocess-windows?limit=0&persist=true"
```

### Reconstruir historial desde registros crudos

```bash
curl -X POST "http://localhost:8000/run/rebuild-windows-from-raw?limit=0&persist=true" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

---

## Preguntas Comunes

**P: Si no hay historial suficiente, el sistema no detecta ataques?**
A: Sí detecta correlaciones fuertes por reglas actuales. Lo que no puede hacer bien aún es comparar contra el comportamiento normal histórico.

**P: Por qué `historical_rows` y `model_rows` pueden ser distintos?**
A: `historical_rows` viene de `WINDOW_METRICS`; `model_rows` viene de `WINDOW_FEATURES`, que excluye ventanas no aptas para entrenamiento.

**P: Por qué antes se quedaba en 1 fila histórica?**
A: Algunas ingestas reutilizaban el mismo `WINDOW_KEY` y HANA hacía `UPSERT`. Ahora las ventanas se derivan de timestamps reales de registros.

**P: Qué pasa si falla SAP SOC API?**
A: La ingesta registra fallo y el sistema sigue sirviendo el último estado persistido.

**P: Qué pasa si falla HANA?**
A: El sistema escribe en SQLite como fallback/respaldo y sincroniza cuando HANA regresa.

**P: Datos antiguos se borran?**
A: Sí. La retención por defecto es 90 días, configurable, con limpieza automática/manual.

---

## Para No Técnicos

Piensa en el sistema como una central de monitoreo:

1. Recibe eventos de SAP.
2. Los ordena por tiempo.
3. Resume cada bloque de 30 minutos.
4. Busca combinaciones peligrosas ahora mismo.
5. Compara contra el comportamiento histórico cuando ya hay suficientes ventanas.
6. Genera alertas y las muestra en API/tablero/bot.

Si aún falta historial, el sistema no está ciego: solo tiene menos contexto para distinguir "raro para nosotros" vs "grave por reglas actuales".
