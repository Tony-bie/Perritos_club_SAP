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

**Por qué `historical_rows` y `model_rows` pueden diferir?**
`historical_rows` viene de `WINDOW_METRICS`; `model_rows` viene de `WINDOW_FEATURES`, que filtra ventanas no aptas para entrenamiento.

**Por qué existe `/run/rebuild-windows-from-raw`?**
Para reconstruir ventanas cuando ya existen registros crudos pero las métricas históricas fueron insuficientes o se sobrescribieron.

**Se puede correr sin HANA?**
Sí. Usa SQLite para desarrollo y demo local. En modo HANA, SQLite también funciona como fallback cuando el primario se cae.
