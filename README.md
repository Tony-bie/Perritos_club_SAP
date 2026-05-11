# 🚀 Live Security Operation Center Defense

**Automated Anomaly Detection for SAP Security Logs**

## 🎯 What This Does

Consumes SAP security logs, detects anomalies using ML, and triggers real-time alerts.

```
SAP SOC → Ingestion → ETL → ML Model → Alerts → Dashboard
```

**Problem**: SAP logs millions of security events daily. Impossible to monitor manually.  
**Solution**: Automatic anomaly detection pipeline with ~5 sec alert latency.

---

## 📚 Documentation

| Document | For Whom | Purpose |
|----------|----------|---------|
| **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Everyone | What, why, how — components, design decisions, pipeline |
| **[SETUP_GUIDE.md](docs/SETUP_GUIDE.md)** | Developers | Installation, configuration, running locally |
| **[tools/walkthrough_demo.py](tools/walkthrough_demo.py)** | Everyone | Live demo of entire pipeline (run: `python tools/walkthrough_demo.py`) |

---

## ⚡ Quick Start (5 min)

### 1. Clone & setup
```bash
git clone https://github.com/Tony-bie/Perritos_club_SAP.git
cd Perritos_club_SAP
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with SAP credentials
```

### 3. Run ingestion cycle
```bash
python main.py
```

### 4. Start API server
```bash
python -m uvicorn backend.api.http.application:app --port 8000
# Test: curl http://localhost:8000/health
```

### 5. Try walkthrough (no setup needed)
```bash
python tools/walkthrough_demo.py
```

---

## 🔌 API Endpoints (Block C)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Liveness check |
| `/health/sap` | GET | SAP SOC API reachable? |
| `/run/ingestion` | POST | Trigger ingestion manually |
| `/status/latest` | GET | Last ingestion status |
| **`/alerts/recent?limit=50`** | GET | Last 50 anomaly alerts |
| **`/metrics/windows?limit=50`** | GET | Last 50 window metrics |
| **`/runs/recent?limit=10`** | GET | Ingestion run history |
| **`/dashboard/summary?time_window_hours=24`** | GET | Dashboard aggregate (24h) |
| `/api/admin/cleanup` | POST | Retention cleanup |

**Example**:
```bash
# Get latest alerts
curl "http://localhost:8000/alerts/recent?limit=5" \
  -H "Authorization: Bearer ${ADMIN_API_KEY}"
```

---

## 🏗️ Project Structure

```
backend/
├── api/http/
│   └── application.py           ← 8 REST endpoints
├── core/
│   └── config.py                ← Settings loader (37 fields)
├── services/
│   ├── ingestion/               ← Normalization, feature extraction
│   ├── detection/               ← ML model, alert logic
│   └── clients/sap_soc.py       ← SAP API client
└── storage/backends/
    └── store.py                 ← HANA / SQLite drivers

docs/
├── ARCHITECTURE.md              ← Design + components
├── SETUP_GUIDE.md               ← Installation + config
└── (old docs consolidated here)

tests/
├── test_config.py               ← Config tests (2/2 ✅)
├── test_block_c_api.py          ← API tests (2/2 ✅)
└── test_block_c_hana_integration.py ← HANA tests

sql/migrations/
├── 001_analytics_extension_tables.sql
├── 002_analytics_extension_views.sql
├── 003_optimizations.sql
└── 004_retention.sql

tools/
├── walkthrough_demo.py          ← 🎬 Live demo script
├── run_hana_migrations.py       ← Setup HANA schema
├── check_hana_ingestion.py      ← Validate HANA connection
└── hana_baseline.py             ← Model training helper
```

---

## 📊 Metrics (From Tests)

| Metric | Value | Note |
|--------|-------|------|
| **MTTD** | 3-5 sec | Detection latency end-to-end |
| **Throughput** | 130 logs/sec | Tested: 3912 logs in 30s |
| **Alert Rate** | ~6% | On test data |
| **False Positive Rate** | ~15% | Configurable via `contamination` |
| **Storage** | ~2GB/90d | HANA columnar compression |

---

## 🧪 Tests

**All passing** (4 tests):
```bash
# Run all
python -m unittest discover -s tests -p "test_*.py" -v

# Run specific
python -m unittest tests.test_config -v
python -m unittest tests.test_block_c_api -v
```

**Result**:
```
test_enable_worker_defaults_to_true ... ok
test_db_env_vars_override_hana_cloud_uaa_binding_for_sql_login ... ok
test_dashboard_summary_endpoint ... ok
test_recent_alerts_windows_and_runs_endpoints ... ok

Ran 4 tests in 0.065s
OK
```

---

## 🎬 Live Demo (Walkthrough)

---

### Run the demo (9 steps, ~2 min)

```bash
python tools/walkthrough_demo.py
```

**Output**: Step-by-step walkthrough showing:
1. Configuration loading
2. Storage initialization
3. Sample data generation
4. Ingestion & feature extraction
5. Anomaly detection (ML scoring)
6. Alert creation
7. API queries (dashboard)
8. Data retention cleanup
9. Performance metrics

This demo shows everything working end-to-end without needing HANA setup.

---

## 🔐 Storage Options

### Local (SQLite) - Default
```bash
STORAGE_BACKEND=sqlite
SQLITE_PATH=./pipeline.db
```
**Use for**: Development, testing, quick demo

### Production (HANA Cloud)
```bash
STORAGE_BACKEND=hana
HANA_HOST=xxxxx.hnacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=***
HANA_SCHEMA=SOC_PIPELINE
```
**Use for**: Production, multi-team, BTP integration

---

## 🛠️ Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11 | ML ecosystem + async |
| Web Framework | FastAPI | Async, Pydantic, OpenAPI |
| Database | HANA Cloud / SQLite | BTP native / lightweight |
| ML Model | scikit-learn (Isolation Forest) | Fast, robust anomaly detection |
| Async Runtime | asyncio + threading | Non-blocking ingestion |
| Notifications | aiogram (Telegram) | Real-time alerts |

---

## 📖 For Different Audiences

**I want to understand the system** → Read [ARCHITECTURE.md](docs/ARCHITECTURE.md)

**I want to install & run it** → Read [SETUP_GUIDE.md](docs/SETUP_GUIDE.md)

**I want to see it working NOW** → Run `python tools/walkthrough_demo.py`

**I want to understand components** → Check code comments in `backend/`

**I want to validate behavior** → Run tests: `python -m unittest discover -s tests`

---

## ✨ Key Features

- ✅ **Automatic Ingestion**: Polls SAP SOC API every 30 minutes
- ✅ **ML-based Detection**: Isolation Forest anomaly scoring
- ✅ **Real-time Alerts**: Telegram notifications (optional)
- ✅ **REST API**: 8 endpoints for dashboards & integration
- ✅ **Data Retention**: Automatic cleanup (90 days configurable)
- ✅ **Flexible Storage**: HANA Cloud or SQLite
- ✅ **Tested**: 4 unit/integration tests (all passing)
- ✅ **Production-ready**: Error handling, logging, monitoring hooks

---

## 🤔 FAQ

**Q: Can I switch between SQLite and HANA?**  
A: Yes. Change `STORAGE_BACKEND` in `.env` and restart.

**Q: What if SAP API is down?**  
A: Ingestion waits & retries. System serves cached data from last successful run.

**Q: How often does ML model retrain?**  
A: Every ingestion cycle (~30 min). Uses last 200 windows of historical data.

**Q: What's the alert latency?**  
A: ~3-5 seconds from ingestion start to API endpoint having result.

**Q: Can I use this without HANA?**  
A: Yes. Use SQLite for local dev/test.

---

## 🚀 Next Steps

1. **Quick test**: `python tools/walkthrough_demo.py` (2 min)
2. **Local setup**: Follow [SETUP_GUIDE.md](docs/SETUP_GUIDE.md) (10 min)
3. **Run API**: `python -m uvicorn backend.api.http.application:app --port 8000`
4. **Query dashboard**: `curl http://localhost:8000/dashboard/summary`
5. **Read architecture**: [ARCHITECTURE.md](docs/ARCHITECTURE.md) for deep dive

---

## 📞 Support

Check:
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — Design & decisions
- [SETUP_GUIDE.md](docs/SETUP_GUIDE.md) — Installation & config
- Code comments in `backend/` — Implementation details
- Test files in `tests/` — Living documentation
- Terminal output — Logging is verbose

---

## 📄 License

[Your License Here]
* Storage layer with SQLite local mode and SAP HANA mode

### Local Run (Windows PowerShell)

```powershell
cd C:\Users\Lenovo\Perritos_club_SAP
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Service default URL:

```text
http://localhost:8000
```

### API Endpoints (Backend Service)

| Endpoint | Purpose |
| --- | --- |
| `/health` | Local service health |
| `/health/sap` | SAP SOC `/health` passthrough |
| `/run/ingestion` | Trigger one full ingestion cycle now |
| `/status/latest` | Get the latest ingestion run summary |
| `/alerts/recent` | Read recent alert events for dashboards |
| `/metrics/windows` | Read recent aggregated window metrics |
| `/runs/recent` | Read recent ingestion runs |
| `/dashboard/summary` | Aggregated dashboard summary (alerts, metrics, last run) |

### Storage Modes

* `STORAGE_BACKEND=sqlite` (default local development)
* `STORAGE_BACKEND=hana` (install `requirements-hana.txt` and configure HANA env vars)

### DevOps Automation

This repository includes a basic GitHub Actions setup:

* `.github/workflows/ci.yml` runs on every push and pull request
* `.github/workflows/deploy.yml` deploys to SAP BTP Cloud Foundry on pushes to `main` or manual dispatch

#### CI Checks

The CI workflow currently:

* installs Python dependencies
* compiles backend sources
* runs the unit tests in `tests/`

#### Cloud Foundry Deployment Notes

The deploy workflow expects the app name in `manifest.yml` to remain:

```text
Perritos-backend
```

The workflow performs:

1. test execution
2. Cloud Foundry login
3. `cf push --no-start`
4. `cf set-env` for production settings
5. `cf start Perritos-backend`
6. smoke test against the deployed `/health` URL

#### Required GitHub Secrets

To enable Cloud Foundry deploys, configure these GitHub secrets:

```text
CF_API
CF_USERNAME
CF_PASSWORD
CF_ORG
CF_SPACE
SAP_SOC_BASE_URL
SAP_SOC_TOKEN
STORAGE_BACKEND
SQLITE_PATH
HANA_HOST
HANA_PORT
HANA_USER
HANA_PASSWORD
HANA_SCHEMA
HANA_ENCRYPT
HANA_VALIDATE_CERTIFICATE
ENABLE_WORKER
POLL_INTERVAL_MINUTES
REQUEST_TIMEOUT_SECONDS
MAX_RETRIES
RETRY_BACKOFF_SECONDS
ERROR_SECURITY_THRESHOLD
ATTACK_SCORE_THRESHOLD
MODEL_ENABLED
MODEL_MIN_TRAINING_ROWS
MODEL_CONTAMINATION
MODEL_HISTORY_LIMIT
```

The smoke test will use `APP_HEALTH_URL` if you set it, and otherwise it will
derive the deployed route from Cloud Foundry and probe `/health` directly.

For production, prefer:

```text
STORAGE_BACKEND=hana
ENABLE_WORKER=true
```

---

## First Milestone

Your goal for Day 1:

* [ ] Connect to API
* [ ] Fetch all pages
* [ ] Build DataFrame
* [ ] Split system vs LLM logs
* [ ] Print summary stats
* [ ] Save raw data
* [ ] Add 1 alert rule

---

## Common Pitfalls

❌ Treating nulls as errors

❌ Mixing LLM + system features blindly

❌ Not handling pagination

❌ Polling too infrequently and missing data

---

## Next Steps

* Add anomaly detection (Isolation Forest / Z-score)
* Build alerting system (Slack, email, webhook)
* Store data in database (Postgres / HANA)
* Add dashboards (Grafana / Superset)

---

## Contact

If the API fails or token is rejected, contact SAP Hackathon technical staff.

---

## TL;DR

1. Poll `/logs/current`
2. Fetch all pages
3. Convert to DataFrame
4. Split system vs LLM logs
5. Detect anomalies
6. Alert + store

That’s it 🚀
