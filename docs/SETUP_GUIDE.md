# Guía de Instalación y Operación

**Objetivo**: correr el sistema localmente con SQLite o conectarlo a SAP HANA Cloud.

---

## Requisitos

- Python 3.11 o superior.
- Git.
- Acceso a SAP SOC API (`SAP_SOC_BASE_URL` y `SAP_SOC_TOKEN`).
- Opcional: credenciales de SAP HANA Cloud.
- Opcional: token de Telegram y configuración LiteLLM para chatbot.

---

## Instalación Local

### Linux/macOS

```bash
git clone https://github.com/Tony-bie/Perritos_club_SAP.git
cd Perritos_club_SAP
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Windows PowerShell

```powershell
git clone https://github.com/Tony-bie/Perritos_club_SAP.git
cd Perritos_club_SAP
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` antes de ejecutar.

---

## Configuración Básica `.env`

### SAP SOC

```text
SAP_SOC_BASE_URL=https://...
SAP_SOC_TOKEN=...
ADMIN_API_KEY=...
```

### SQLite local

```text
STORAGE_BACKEND=sqlite
SQLITE_PATH=./pipeline.db
ENABLE_WORKER=false
```

### SAP HANA Cloud

```text
STORAGE_BACKEND=hana
HANA_HOST=...
HANA_PORT=443
HANA_USER=...
HANA_PASSWORD=...
HANA_SCHEMA=SOC_PIPELINE
HANA_ENCRYPT=true
HANA_VALIDATE_CERTIFICATE=false
ENABLE_WORKER=true
```

Con `STORAGE_BACKEND=hana`, el sistema usa SQLite como fallback/respaldo si HANA falla. Cuando HANA vuelve, `ResilientStore` intenta resincronizar lo pendiente hacia HANA.

---

## Configuración de Detección

```text
ERROR_SECURITY_THRESHOLD=25
ATTACK_SCORE_THRESHOLD=70
MODEL_ENABLED=true
MODEL_MIN_TRAINING_ROWS=30
MODEL_HISTORY_LIMIT=200
MODEL_CONTAMINATION=0.15
```

Notas:

- `historical_rows` se calcula desde `WINDOW_METRICS`.
- `model_rows` se calcula desde `WINDOW_FEATURES`.
- Aunque falte historial, las reglas actuales pueden generar alertas de correlación.

---

## Ejecutar el Sistema

### Ingesta manual

```bash
python main.py
```

### API con FastAPI

```bash
python -m uvicorn backend.api.http.application:app --host 0.0.0.0 --port 8000
```

Verifica:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/history/status
curl http://localhost:8000/status/latest
```

### Proceso automático

Activa en `.env`:

```text
ENABLE_WORKER=true
POLL_INTERVAL_MINUTES=30
```

Al iniciar la API, se crea un proceso en segundo plano que ejecuta ciclos de ingesta.

---

## Rutas Útiles

| Ruta | Método | Uso |
|----------|--------|-----|
| `/health` | GET | Estado del servicio |
| `/health/sap` | GET | Estado de SAP SOC |
| `/history/status` | GET | Filas de línea base/modelo |
| `/status/latest` | GET | Última ejecución y última ventana |
| `/alerts/recent?limit=50` | GET | Alertas recientes |
| `/metrics/windows?limit=50` | GET | Ventanas recientes |
| `/runs/recent?limit=10` | GET | Historial de ingestas |
| `/dashboard/summary?time_window_hours=24` | GET | Resumen para tablero |
| `/run/ingestion` | POST | Ingesta manual |
| `/run/reprocess-windows` | POST | Recalcula riesgo |
| `/run/rebuild-windows-from-raw` | POST | Reconstruye ventanas desde registros crudos |
| `/run/resync-fallback` | POST | Sincroniza fallback SQLite -> HANA |
| `/api/admin/cleanup` | POST | Limpieza por retención |

Las rutas admin aceptan:

```bash
-H "Authorization: Bearer $ADMIN_API_KEY"
```

o:

```bash
-H "X-API-Key: $ADMIN_API_KEY"
```

---

## Configuración con SAP HANA Cloud

1. Instala dependencias HANA:

```bash
pip install -r requirements-hana.txt
```

2. Configura variables HANA en `.env`.

3. Ejecuta el esquema base y las migraciones:

```bash
python tools/run_hana_migrations.py
```

4. Valida conexión:

```bash
python tools/check_hana_ingestion.py
```

5. Levanta API y revisa:

```bash
curl http://localhost:8000/health
```

---

## Telegram y Chatbot

El chatbot usa Telegram para la interfaz y LiteLLM para conectar con el proveedor de modelo. `requirements.txt` ya incluye `aiogram` y `litellm`.

Variables principales:

```text
TOKEN_BOT_TELEGRAM=...
CHAT_IDS=123456789,987654321
TELEGRAM_CHATBOT_ENABLED=true
LLM_ENABLED=true
LLM_PROVIDER_MODEL=groq/llama-3.1-8b-instant
LLM_API_KEY=...
LLM_BASE_URL=
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=400
```

Ejemplos de `LLM_PROVIDER_MODEL`:

- `groq/llama-3.1-8b-instant`
- `gemini/gemini-1.5-flash`
- Un modelo servido por tu proxy LiteLLM o gateway local.

`LLM_BASE_URL` se deja vacío para proveedores soportados directamente por LiteLLM. Llénalo solo si usas un proxy propio, gateway local o endpoint compatible.

Comandos del bot:

- `/health`
- `/last_status`
- `/ask qué está pasando con los registros?`

El chatbot arma contexto con instantáneas de rutas útiles como `/health`, `/history/status`, `/status/latest`, `/dashboard/summary`, `/alerts/recent`, `/metrics/windows`, `/runs/recent` y `/health/sap`.

La respuesta indica la fuente:

- `Fuente: llm`: LiteLLM respondió con el modelo configurado.
- `Fuente: fallback`: el sistema usó resumen local porque LiteLLM está apagado, mal configurado, no instalado o el proveedor falló.

El resumen local incluye alertas recientes, alertas de alta severidad, ventanas anómalas, último estado de ingesta, riesgo más reciente y pendientes de SQLite fallback.

---

## Reconstruir Historial

Usa esto si `/history/status` muestra pocas ventanas aunque `RAW_LOGS` tenga datos:

```bash
curl -X POST "http://localhost:8000/run/rebuild-windows-from-raw?limit=0&persist=true" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

Luego revisa:

```bash
curl http://localhost:8000/history/status
curl http://localhost:8000/status/latest
```

---

## Pruebas

Todas las pruebas:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Pruebas enfocadas:

```bash
python -m unittest tests.test_features tests.test_detection tests.test_store_fallback
```

Validación de sintaxis:

```bash
python -m py_compile backend/api/http/application.py backend/services/ingestion/features.py backend/storage/backends/store.py
```

---

## Solución de Problemas

### `ModuleNotFoundError`

Activa el virtualenv e instala dependencias:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

En Windows:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### `/health` marca almacenamiento degradado

Revisa variables HANA/SQLite en `.env`. Si usas HANA, valida host, usuario, password y esquema.

### `/history/status` muestra historial insuficiente

Revisa cuántas ventanas existen:

```bash
curl http://localhost:8000/history/status
```

Si hay registros crudos pero pocas ventanas, reconstruye:

```bash
curl -X POST "http://localhost:8000/run/rebuild-windows-from-raw?limit=0&persist=true" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

### HANA falla pero SQLite tiene pendientes

Revisa `/health`. Si hay `fallback.pending_counts`, fuerza la resincronización cuando HANA vuelva:

```bash
curl -X POST http://localhost:8000/run/resync-fallback \
  -H "X-API-Key: $ADMIN_API_KEY"
```

### SAP SOC responde 401/422

Revisa `SAP_SOC_TOKEN` y `SAP_SOC_BASE_URL`.

### Las pruebas de HANA se saltan

Es normal si no hay credenciales HANA configuradas localmente.

---

## Siguientes Pasos Recomendados

1. Ejecutar demo local.
2. Configurar `.env` real.
3. Levantar API.
4. Ejecutar `/run/ingestion`.
5. Ver `/history/status` y `/status/latest`.
6. Reconstruir desde registros crudos si hace falta.
7. Conectar tablero o bot.
