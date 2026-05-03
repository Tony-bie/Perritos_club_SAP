# SAP SOC Log Ingestion Pipeline

## Overview

This project consumes real-time SAP SOC logs and processes them for security analysis, anomaly detection, and alerting.

The API provides logs in **rolling 30-minute windows**, and our pipeline is responsible for:

* Ingesting logs continuously
* Normalizing system vs LLM logs
* Detecting anomalies and threats
* Storing data for analysis
* Triggering alerts

---

## Architecture (High Level)

```
SAP SOC API → Ingestion → Normalization → Feature Engineering → Detection → Alerts + Storage
```

---

## API Basics

### Base Endpoints

| Endpoint        | Purpose                  |
| --------------- | ------------------------ |
| `/health`       | Liveness check (no auth) |
| `/info`         | Batch size + total pages |
| `/logs/current` | Main ingestion endpoint  |

### Authentication

All endpoints (except `/health`) require:

```
Authorization: Bearer <your-token>
```

---

## Time Window Behavior (IMPORTANT)

The API always returns the **current UTC 30-minute window**.

| Server Minute | Window          |
| ------------- | --------------- |
| 00–29         | HH:00 → HH:30   |
| 30–59         | HH:30 → HH+1:00 |

⚠️ You do NOT pass timestamps — the server decides.

---

## Pagination Strategy

You must:

1. Request page 1
2. Read `total_pages`
3. Loop through remaining pages

---

## Quick Start

### 1. Install dependencies

```bash
pip install requests pandas
```

### 2. Environment variables

```bash
export SAP_SOC_BASE_URL=http://localhost:8000
export SAP_SOC_TOKEN=your-token
```

### 3. Run ingestion script

```bash
python main.py
```

---

## Minimal Working Example

```python
import os
import requests
import pandas as pd

BASE_URL = os.getenv("SAP_SOC_BASE_URL")
TOKEN = os.getenv("SAP_SOC_TOKEN")

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# Fetch first page
r = requests.get(f"{BASE_URL}/logs/current", headers=HEADERS, params={"page": 1})
payload = r.json()

records = payload["data"]

# Fetch remaining pages
for page in range(2, payload["total_pages"] + 1):
    r = requests.get(f"{BASE_URL}/logs/current", headers=HEADERS, params={"page": page})
    records.extend(r.json()["data"])

# Convert to DataFrame
df = pd.DataFrame(records)
print(df.head())
```

---

## Log Types

### System Logs

Examples:

* INFO
* WARNING
* ERROR
* SECURITY
* AUDIT

Key fields:

* `client_ip`
* `service_id`
* `http_status_code`

### LLM Logs

Examples:

* LLM_REQUEST
* LLM_ERROR
* LLM_TIMEOUT

Key fields:

* `llm_model_id`
* `llm_status`
* `llm_cost_usd`
* `llm_response_time_ms`

---

## ⚠️ Critical Data Rule

The dataset intentionally contains **null patterns**:

* LLM logs → system fields are empty
* System logs → llm fields are empty

DO NOT treat this as bad data.

---

## Recommended Normalization

```python
llm_types = {"LLM_REQUEST", "LLM_ERROR", "LLM_TIMEOUT"}

df["is_llm_log"] = df["sap_function_log_type"].isin(llm_types)
df["is_system_log"] = ~df["is_llm_log"]
```

---

## Basic Analysis (First Step)

```python
print(df["sap_function_log_type"].value_counts())
print(df["client_ip"].value_counts().head())
```

---

## Detection Ideas (Start Simple)

### System Threats

* Many ERROR/SECURITY events from one IP
* Same IP hitting many services
* High rate of 4xx/5xx responses

### LLM Threats

* Spike in LLM_TIMEOUT
* High latency
* Sudden cost increase
* Error rate increase

---

## Example Feature Engineering

### System

```python
system_df = df[df["is_system_log"]]

features = system_df.groupby("client_ip").agg(
    event_count=("sap_function_log_type", "count"),
    error_count=("sap_function_log_type", lambda s: (s == "ERROR").sum()),
)
```

### LLM

```python
llm_df = df[df["is_llm_log"]]

features = llm_df.groupby("llm_model_id").agg(
    avg_latency=("llm_response_time_ms", "mean"),
    total_cost=("llm_cost_usd", "sum"),
)
```

---

## Scheduling

Recommended:

* Poll every **5 minutes**, OR
* Poll every **30 minutes** exactly

Use `_id` to deduplicate records.

---

## Storage Recommendation

| Field        | Usage       |
| ------------ | ----------- |
| `_id`        | Primary key |
| `@timestamp` | Time index  |

Optional:

* `is_llm_log`
* `is_system_log`
* `ingested_at`

---

## Project Structure

```
project/
├── backend/
│   ├── api/
│   │   └── http/
│   │       └── application.py
│   ├── core/
│   │   └── config.py
│   ├── services/
│   │   ├── clients/
│   │   │   └── sap_soc.py
│   │   ├── detection/
│   │   │   ├── alert.py
│   │   │   ├── detect.py
│   │   │   └── model.py
│   │   └── ingestion/
│   │       ├── features.py
│   │       ├── ingest.py
│   │       └── normalize.py
│   └── storage/
│       └── backends/
│           └── store.py
├── docs/
│   └── HANA_CONNECTION.md
├── scripts/
│   └── test_hana_connection.py
├── main.py
├── test_hana_connection.py
├── requirements.txt
├── requirements-hana.txt
└── .env.example
```

---

## Backend Base (Implemented)

The backend scaffold is now available with:

* FastAPI service endpoints
* SAP SOC ingestion client (`/info` + paginated `/logs/current?page=N`)
* Normalization flags (`is_llm_log`, `is_system_log`)
* MVP detection rule (ERROR/SECURITY spike by `client_ip`)
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
