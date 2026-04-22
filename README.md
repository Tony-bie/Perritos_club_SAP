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
SAP SOC API → Cloud Foundry Ingestion App → Feature Engineering + Detection → SAP HANA Cloud + Alerts
```

SAP-first deployment split:

* `Cloud Foundry app` runs the polling pipeline and scoring logic.
* `SAP HANA Cloud` stores raw logs, window metrics, detections, and labels for retraining.
* `SAP Alert Notification` can be wired later to publish confirmed incidents.

Official references used for this setup:

* SAP BTP Python on Cloud Foundry: https://help.sap.com/docs/btp/sap-business-technology-platform/developing-python-in-cloud-foundry-environment
* SAP BTP Cloud Foundry runtime overview: https://help.sap.com/docs/cf-runtime/cloud-foundry-runtime/what-is-sap-btp-cloud-foundry-runtime
* `hana-ml` overview: https://help.sap.com/doc/1d0ebfe5e8dd44d09606814d83308d4b/2.0.08/en-US/hana_ml.html
* `hana-ml` installation: https://help.sap.com/doc/cd94b08fe2e041c2ba778374572ddba9/2025_3_QRC/en-US/Installation.html
* `ConnectionContext`: https://help.sap.com/doc/1d0ebfe5e8dd44d09606814d83308d4b/2.0.08/en-US/hana_ml.dataframe.html
* PAL Isolation Forest: https://help.sap.com/docs/hana-cloud-database/sap-hana-cloud-sap-hana-database-predictive-analysis-library/isolation-forest-isolation-forest-11345d9
* `hana_ml.algorithms.pal.preprocessing.IsolationForest`: https://help.sap.com/doc/1d0ebfe5e8dd44d09606814d83308d4b/2.0.08/en-US/pal/algorithms/hana_ml.algorithms.pal.preprocessing.IsolationForest.html

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
python3 -m pip install -r requirements.txt
```

### 2. Environment variables

```bash
cp .env.example .env
```

Then update `.env` with your real API values.

If you want to connect directly to SAP HANA Cloud, you can also start from:

```bash
cp .env.hana.example .env
```

### 3. Run ingestion once

```bash
python3 main.py once
```

### 4. Train the hana-ml model

```bash
python3 main.py train
```

### 5. Run continuous polling

```bash
python3 main.py poll --interval-seconds 1800
```

### 6. Run with Docker

Build the image:

```bash
docker build -t sap-soc-pipeline:local .
```

Run the web app:

```bash
docker run --rm -p 8080:8080 --env-file .env --name sap-soc-pipeline sap-soc-pipeline:local
```

Health check:

```bash
curl http://127.0.0.1:8080/health
```

### 7. Deploy to SAP BTP Cloud Foundry

This repo is already prepared for SAP BTP Cloud Foundry with:

* `manifest.yml` for the web app
* `manifest.worker.yml` for an optional background polling worker
* `Procfile` / `gunicorn` to expose the Flask app on `$PORT`

Login first:

```bash
cf login -a https://api.cf.us10.hana.ondemand.com
cf target -o <your-org> -s <your-space>
```

Deploy the web app:

```bash
cf push
```

Set the SOC API settings on the deployed app:

```bash
cf set-env sap-soc-pipeline SAP_SOC_BASE_URL https://your-soc-api.example.com
cf set-env sap-soc-pipeline SAP_SOC_TOKEN your-real-token
cf restage sap-soc-pipeline
```

Useful routes after deploy:

* `GET /` - basic app info and whether HANA was detected
* `GET /health` - liveness check
* `POST /ingest/current` - ingest the current 30-minute window
* `POST /train` - train the HANA ML model when enough rows exist

If you want the pipeline to poll continuously inside Cloud Foundry instead of calling `/ingest/current` manually, deploy the worker too:

```bash
cf push -f manifest.worker.yml
```

The worker runs:

```bash
python main.py poll --interval-seconds 1800
```

Keep the worker at `instances: 1` unless you also add a locking strategy, otherwise multiple workers can ingest the same window.

---

## What the starter now does

* Calls `/info`
* Fetches page 1 from `/logs/current`
* Reads `total_pages` and downloads the remaining pages
* Builds a pandas `DataFrame`
* Adds `is_llm_log` and `is_system_log`
* Deduplicates on `_id` when present
* Builds `window`, `client_ip`, and `llm_model_id` feature sets
* Runs hybrid detection rules and produces a threat score
* If SAP HANA is configured and enough history exists, scores the current 30-minute window with `hana_ml` before making the final decision
* Saves each 30-minute window under `data/batches/<window_key>/`
* Automatically tries SAP HANA when credentials are present in `SAP_HANA_*` or a Foundry `VCAP_SERVICES` binding

Files saved per window:

* `raw.json` - raw API payload records
* `normalized.csv` - normalized flat table for analysis
* `window_metrics.json` - feature summary for the batch
* `ip_features.csv` - aggregated system behavior per IP
* `llm_features.csv` - aggregated LLM behavior per model
* `detections.json` - rules triggered in that window
* `summary.json` - counts, pages, threat score, and metadata

The script also writes:

* `data/ingestion_state.json` - last processed window
* `data/window_metrics_history.csv` - rolling training base for future labeling and retraining

The default polling cadence is now one ingestion every 30 minutes so each run matches one SOC window.

---

## SAP HANA Mode

If you provide `SAP_HANA_HOST`, `SAP_HANA_PORT`, `SAP_HANA_USER`, and `SAP_HANA_PASSWORD`, the pipeline also writes to SAP HANA.

In Cloud Foundry, the app also tries to discover a bound HANA service automatically from `VCAP_SERVICES`. If more than one HANA-like service is bound, set `SAP_HANA_SERVICE_NAME` to the exact binding name you want to use.

For SAP HANA Cloud Free Tier, SAP allows connections from apps running in the same SAP BTP Cloud Foundry region by default, while local tools such as DBeaver are blocked unless IP rules are changed on supported tiers. That means your easiest path is:

1. Deploy the app to Cloud Foundry
2. Bind a HANA service instance if you have one available in the same space
3. Or set `SAP_HANA_*` app env vars with `cf set-env` and restage the app

Example:

```bash
cf set-env sap-soc-pipeline SAP_HANA_HOST your-sql-endpoint.hna1.prod-us10.hanacloud.ondemand.com
cf set-env sap-soc-pipeline SAP_HANA_PORT 443
cf set-env sap-soc-pipeline SAP_HANA_USER DBADMIN
cf set-env sap-soc-pipeline SAP_HANA_PASSWORD your-password
cf set-env sap-soc-pipeline SAP_HANA_SCHEMA SOC_PIPELINE
cf set-env sap-soc-pipeline SAP_HANA_ENCRYPT true
cf set-env sap-soc-pipeline SAP_HANA_VALIDATE_CERTIFICATE false
cf restage sap-soc-pipeline
```

Tables created or expected:

* `RAW_LOGS`
* `WINDOW_METRICS`
* `DETECTIONS`
* `TRAINING_LABELS`
* `MODEL_RUNS`
* `MODEL_SCORES`

You can pre-create them by running the SQL in `sql/hana_setup.sql` from SAP HANA Database Explorer or your deployment flow.

## hana-ml Training

The project now includes a training path that imports:

```python
from hdbcli import dbapi
import hana_ml
```

Training uses `hana_ml.dataframe.ConnectionContext` and the PAL `IsolationForest` wrapper over the accumulated `WINDOW_METRICS` table.

Current flow:

* ingest batches into `RAW_LOGS` and `WINDOW_METRICS`
* run `python3 main.py train`
* store run metadata in `MODEL_RUNS`
* store scored windows in `MODEL_SCORES`

Live decision flow every 30 minutes:

* ingest the current `/logs/current` window
* compute window features
* if enough HANA history exists, score the current window with `IsolationForest`
* combine `rule_score` and `ml_confidence_score`
* emit a final `attack_predicted` for that window

Important SAP-side prerequisites:

* PAL Isolation Forest requires no missing values in the training input
* your HANA user needs PAL roles such as `AFL__SYS_AFL_AFLPAL_EXECUTE`

## Cloud Foundry Hosting

The repo now includes:

* [manifest.yml](/home/andre/projects/hackathon/Perritos_club_SAP/manifest.yml)
* [Procfile](/home/andre/projects/hackathon/Perritos_club_SAP/Procfile)
* [foundry_app.py](/home/andre/projects/hackathon/Perritos_club_SAP/foundry_app.py)

Foundry endpoints:

* `GET /health`
* `POST /ingest/current`
* `POST /train`

Example deploy:

```bash
cf push
```

This uses SAP BTP Cloud Foundry's `python_buildpack`, which SAP documents as supported for Python applications.

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

The included `poll` mode already handles "same window seen again" by skipping windows it has already stored locally.

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
├── main.py
├── soc_pipeline/
│   ├── application/
│   ├── domain/
│   ├── infrastructure/
│   └── shared/
├── requirements.txt
├── .env.example
├── .env.hana.example
└── sql/
    └── hana_setup.sql
```

---

## First Milestone

Your goal for Day 1:

* [ ] Connect to API
* [ ] Fetch all pages
* [ ] Build DataFrame
* [ ] Split system vs LLM logs
* [ ] Save raw data and feature history
* [ ] Score 2 windows per hour
* [ ] Persist metrics to SAP HANA
* [ ] Add manual labels in `TRAINING_LABELS`

---

## Common Pitfalls

❌ Treating nulls as errors

❌ Mixing LLM + system features blindly

❌ Not handling pagination

❌ Polling too infrequently and missing data

---

## Next Steps

* Add Alert Notification integration for confirmed attacks
* Train anomaly models in SAP HANA PAL or via `hana-ml`
* Join labels from `TRAINING_LABELS` with `WINDOW_METRICS` for retraining
* Add dashboards in SAP Analytics Cloud or another BI layer

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
