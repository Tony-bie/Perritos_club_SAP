from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException

from alert import format_alert_events
from client import SAPSOCClient
from config import load_settings
from detect import detect_error_security_spike
from ingest import ingest_result_to_dict, run_ingestion_cycle
from normalize import normalize_records
from store import create_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("sap_soc_backend")

settings = load_settings()
store = create_store(settings)
client = SAPSOCClient(
    base_url=settings.sap_soc_base_url,
    token=settings.sap_soc_token,
    timeout_seconds=settings.request_timeout_seconds,
    max_retries=settings.max_retries,
    retry_backoff_seconds=settings.retry_backoff_seconds,
)

app = FastAPI(title="SAP SOC Backend", version="0.1.0")
_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None


def execute_ingestion_cycle() -> Dict[str, Any]:
    run_id = str(uuid4())
    ingest_result, records = run_ingestion_cycle(client, run_id=run_id)
    run_data = ingest_result_to_dict(ingest_result)

    if ingest_result.status != "success":
        store.insert_ingest_run(run_data)
        return {
            "run": run_data,
            "upserted_records": 0,
            "alerts_count": 0,
        }

    normalized = normalize_records(records)
    upserted = store.upsert_raw_logs(normalized)

    raw_alerts = detect_error_security_spike(
        normalized_records=normalized,
        combined_threshold=settings.error_security_threshold,
    )
    alert_events = format_alert_events(raw_alerts, run_id=run_id)
    alerts_inserted = store.insert_alerts(alert_events)

    store.insert_ingest_run(run_data)

    return {
        "run": run_data,
        "upserted_records": upserted,
        "alerts_count": alerts_inserted,
    }


def _worker_loop() -> None:
    logger.info("Background worker started. Poll interval: %s minutes", settings.poll_interval_minutes)
    while not _stop_event.is_set():
        try:
            result = execute_ingestion_cycle()
            logger.info(
                "Ingestion cycle finished. run_id=%s status=%s records=%s alerts=%s",
                result["run"].get("run_id"),
                result["run"].get("status"),
                result.get("upserted_records"),
                result.get("alerts_count"),
            )
        except Exception as exc:
            logger.exception("Worker cycle failed: %s", exc)

        wait_seconds = max(1, settings.poll_interval_minutes * 60)
        _stop_event.wait(wait_seconds)


@app.on_event("startup")
def on_startup() -> None:
    store.ensure_schema()

    global _worker_thread
    if settings.enable_worker:
        _worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        _worker_thread.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    _stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=5)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "worker_enabled": settings.enable_worker,
        "storage_backend": settings.storage_backend,
    }


@app.get("/health/sap")
def health_sap() -> Dict[str, Any]:
    try:
        return client.get_health()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/run/ingestion")
def run_ingestion() -> Dict[str, Any]:
    try:
        return execute_ingestion_cycle()
    except Exception as exc:
        logger.exception("Manual ingestion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/status/latest")
def status_latest() -> Dict[str, Any]:
    latest = store.get_last_run()
    if not latest:
        return {"status": "no-runs-yet"}
    return {"status": "ok", "latest_run": latest}


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.app_host, port=settings.app_port, reload=False)
