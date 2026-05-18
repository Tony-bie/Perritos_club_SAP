# Live Security Operation Center Defense

Backend para ingerir registros de SAP SOC, agruparlos en ventanas de 30 minutos, detectar correlaciones/anomalías y exponer estado para tableros, Telegram y chatbot.

## Qué Hace

```text
SAP SOC API -> Ingesta -> Normalización -> RAW_LOGS -> WINDOW_METRICS -> Riesgo/Alertas -> API/Tablero/Bot
```

El sistema combina:

- Reglas de correlación actuales para detectar señales fuertes aunque falte historial.
- Línea base histórica desde `WINDOW_METRICS` para comparar contra comportamiento normal.
- Modelo HANA ML desde `WINDOW_FEATURES` cuando hay suficientes features limpias.
- SQLite como fallback/respaldo local cuando HANA no está disponible.
- Resincronización automática o manual del fallback cuando HANA vuelve.
- Chatbot Telegram con LiteLLM para explicar el estado usando las rutas útiles del backend.

## Documentación

| Documento | Para quién | Contenido |
|-----------|------------|-----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Todos | Arquitectura real, flujo de datos, línea base/modelo/fallback |
| [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md) | Equipo técnico/Ops | Instalación, configuración, rutas y solución de problemas |
| [docs/INDEX.md](docs/INDEX.md) | Todos | Índice rápido de documentación |
| [tools/walkthrough_demo.py](tools/walkthrough_demo.py) | Demo | Simulación local sin HANA |

## Inicio Rápido

```bash
git clone https://github.com/Tony-bie/Perritos_club_SAP.git
cd Perritos_club_SAP
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

En Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` con tus credenciales de SAP SOC y el backend deseado (`sqlite` o `hana`).

Para evitar bloqueos `429 Too Many Requests` del proveedor SAP SOC, deja una pausa mínima entre llamadas y respeta ventanas de reintento:

```text
POLL_INTERVAL_MINUTES=30
SAP_SOC_MIN_REQUEST_INTERVAL_SECONDS=1.0
SAP_SOC_MAX_RETRY_AFTER_SECONDS=300
MAX_RETRIES=3
RETRY_BACKOFF_SECONDS=2
```

## Ejecutar

Una ingesta manual:

```bash
python main.py
```

Servidor API:

```bash
python -m uvicorn backend.api.http.application:app --port 8000
curl http://localhost:8000/health
```

Demo local:

```bash
python tools/walkthrough_demo.py
```

## Rutas Principales

| Ruta | Método | Propósito |
|----------|--------|-----------|
| `/health` | GET | Estado del servicio, almacenamiento, proceso en segundo plano y respaldo |
| `/health/sap` | GET | Verifica conectividad con SAP SOC |
| `/history/status` | GET | Estado de la línea base histórica y el modelo |
| `/status/latest` | GET | Última ejecución y última ventana |
| `/alerts/recent?limit=50` | GET | Alertas recientes |
| `/metrics/windows?limit=50` | GET | Ventanas recientes |
| `/runs/recent?limit=10` | GET | Ejecuciones de ingesta recientes |
| `/dashboard/summary?time_window_hours=24` | GET | Agregado para tablero |
| `/run/ingestion` | POST | Ejecuta ingesta manual |
| `/run/reprocess-windows` | POST | Recalcula riesgo de ventanas existentes |
| `/run/rebuild-windows-from-raw` | POST | Reconstruye ventanas desde `RAW_LOGS` |
| `/run/resync-fallback` | POST | Sincroniza el fallback SQLite hacia HANA |
| `/api/admin/cleanup` | POST | Limpieza por retención |

Las rutas administrativas usan `Authorization: Bearer <token>` o `X-API-Key: <token>`.

## Telegram y LiteLLM

El bot puede mandar estado y responder preguntas operativas con `/ask`. Usa LiteLLM para llamar al proveedor configurado, pero no depende ciegamente del LLM: si LiteLLM está deshabilitado, no está instalado, no tiene modelo/API key o el proveedor falla, responde con un resumen local.

```text
TOKEN_BOT_TELEGRAM=...
CHAT_IDS=123456789
TELEGRAM_CHATBOT_ENABLED=true
LLM_ENABLED=true
LLM_PROVIDER_MODEL=groq/llama-3.1-8b-instant
LLM_API_KEY=...
LLM_BASE_URL=
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=400
```

Modelos típicos en `LLM_PROVIDER_MODEL`: `groq/llama-3.1-8b-instant`, `gemini/gemini-1.5-flash` o el nombre que acepte tu gateway LiteLLM. `LLM_BASE_URL` solo se usa para proxy propio o gateway local.

El contexto que recibe el modelo sale de `/health`, `/history/status`, `/status/latest`, `/dashboard/summary`, `/alerts/recent`, `/metrics/windows`, `/runs/recent` y `/health/sap`. La respuesta final indica `Fuente: llm` o `Fuente: fallback`.

## Comandos Útiles

Estado operativo:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/history/status
curl http://localhost:8000/status/latest
```

Reconstruir historial desde registros crudos:

```bash
curl -X POST "http://localhost:8000/run/rebuild-windows-from-raw?limit=0&persist=true" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

Reprocesar ventanas existentes:

```bash
curl -X POST "http://localhost:8000/run/reprocess-windows?limit=0&persist=true"
```

## Estructura del Proyecto

```text
backend/
├── api/http/application.py       # API REST, proceso en segundo plano, rutas admin
├── core/config.py                # Carga de configuración
├── services/
│   ├── ingestion/                # Normalización, ventanas, features
│   ├── detection/                # Línea base, modelo, reglas, alertas
│   └── clients/sap_soc.py        # Cliente SAP SOC
└── storage/backends/store.py     # HANA, SQLite fallback y ResilientStore

docs/
├── ARCHITECTURE.md
├── SETUP_GUIDE.md
└── INDEX.md

tests/
├── test_features.py
├── test_detection.py
├── test_store_fallback.py
├── test_block_c_api.py
└── test_block_c_hana_integration.py
```

## Almacenamiento

### SQLite local

```text
STORAGE_BACKEND=sqlite
SQLITE_PATH=./pipeline.db
```

### SAP HANA Cloud

```text
STORAGE_BACKEND=hana
HANA_HOST=...
HANA_PORT=443
HANA_USER=...
HANA_PASSWORD=...
HANA_SCHEMA=SOC_PIPELINE
```

Con `STORAGE_BACKEND=hana`, el sistema usa SQLite como fallback/respaldo resiliente si HANA falla. Cuando HANA vuelve, `ResilientStore` intenta subir lo pendiente al primario.

## Pruebas

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Pruebas enfocadas:

```bash
python -m unittest tests.test_features tests.test_detection tests.test_store_fallback
```

## Preguntas Rápidas

**Si falta historial, no detecta ataques?**
No. Las reglas actuales siguen generando alertas fuertes. Lo que falta es comparación histórica fina.

**El modelo necesita activarse con entrenamiento?**
No para detectar. La ingesta y las reglas están activas desde el primer ciclo; el historial y el modelo solo calibran mejor la señal de anomalías.

**Si aparece algo por primera vez es anomalía?**
Sí, se marca como `novel_activity`: algo nuevo observado. Eso no implica ataque por sí solo, pero sí queda señalado para revisión.

**Por qué `historical_rows` y `model_rows` pueden diferir?**
`historical_rows` viene de `WINDOW_METRICS`; `model_rows` viene de `WINDOW_FEATURES`, que filtra ventanas no aptas para entrenamiento.

**Por qué existe `/run/rebuild-windows-from-raw`?**
Para reconstruir ventanas cuando ya existen registros crudos pero las métricas históricas fueron insuficientes o se sobrescribieron.

**Se puede correr sin HANA?**
Sí. Usa SQLite para desarrollo y demo local. En modo HANA, SQLite también funciona como fallback cuando el primario se cae.
