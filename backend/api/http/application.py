from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from backend.core.config import load_settings
from backend.services.clients import SAPSOCClient
from backend.services.detection import (
    build_alert_submission_message,
    evaluate_window_risk,
    format_alert_events,
    score_historical_pattern,
    score_window_metrics,
    should_submit_alert_notification,
    unavailable_model_signal,
)
from backend.services.ingestion import (
    build_window_metrics,
    ingest_result_to_dict,
    normalize_records,
    run_ingestion_cycle,
)
from backend.storage import create_store

from aiogram import Bot, Router, Dispatcher
from aiogram.types import Message

from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import asyncio

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

token = settings.token_bot_telegram
chat_ids = settings.chat_ids
bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

app = FastAPI(title="SAP SOC Backend", version="0.1.0")
_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None
_storage_status: Dict[str, Any] = {
    "ready": False,
    "error": None,
}

router = Router(name= __name__)
dp = Dispatcher() 
dp.include_router(router)

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
    window_metrics = build_window_metrics(
        normalized_records=normalized,
        window_start=ingest_result.window_start,
        window_end=ingest_result.window_end,
    )
    store.upsert_window_metrics(window_metrics)
    current_window_key = str(window_metrics.get("window_key") or "")
    history_rows = store.get_recent_window_features(limit=settings.model_history_limit)
    history_rows = [
        row
        for row in history_rows
        if str(row.get("window_key") or "") != current_window_key
    ]

    historical_signal = score_historical_pattern(
        current_metrics=window_metrics,
        history_rows=history_rows,
        min_history_rows=max(20, settings.model_min_training_rows),
    )

    model_signal = (
        score_window_metrics(
            settings=settings,
            current_window_key=current_window_key,
            min_training_rows=settings.model_min_training_rows,
            contamination=settings.model_contamination,
        )
        if settings.model_enabled
        else unavailable_model_signal("model_disabled")
    )
    raw_alerts, risk_summary = evaluate_window_risk(
        normalized_records=normalized,
        metrics=window_metrics,
        model_signal=model_signal,
        historical_signal=historical_signal,
        count_threshold=settings.error_security_threshold,
        attack_score_threshold=settings.attack_score_threshold,
    )
    window_metrics.update(risk_summary)
    window_metrics["run_id"] = run_id
    store.upsert_window_metrics(window_metrics)
    alert_events = format_alert_events(raw_alerts, run_id=run_id)
    alerts_inserted = store.insert_alerts(alert_events)
    submitted_alert_response: Dict[str, Any] | None = None
    submitted_alert_error: str | None = None
    submitted_alert_message: str | None = None
    submitted_alert_eligible = False
    submitted_alert_reason = "no_detection_signals"

    submitted_alert_eligible, submitted_alert_reason = should_submit_alert_notification(
        window_metrics=window_metrics,
        raw_alerts=raw_alerts,
        attack_score_threshold=settings.attack_score_threshold,
    )

    if submitted_alert_eligible:
        submitted_alert_message = build_alert_submission_message(
            window_metrics=window_metrics,
            raw_alerts=raw_alerts,
            notification_reason=submitted_alert_reason,
        )
        try:
            submitted_alert_response = client.submit_alert(submitted_alert_message)
        except Exception as exc:
            submitted_alert_error = str(exc)
            logger.warning(
                "Failed to submit alert to SAP endpoint. run_id=%s error=%s",
                run_id,
                exc,
            )

    store.insert_ingest_run(run_data)

    return {
        "run": run_data,
        "upserted_records": upserted,
        "alerts_count": alerts_inserted,
        "alert_submission": {
            "attempted": bool(raw_alerts),
            "eligible": submitted_alert_eligible,
            "eligibility_reason": submitted_alert_reason,
            "message": submitted_alert_message,
            "submitted": submitted_alert_response is not None,
            "response": submitted_alert_response,
            "error": submitted_alert_error,
        },
        "window_metrics": window_metrics,
        "model": model_signal,
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
    try:
        store.ensure_schema()
    except Exception as exc:
        _storage_status["ready"] = False
        _storage_status["error"] = str(exc)
        logger.exception("Storage backend unavailable during startup: %s", exc)
        return

    _storage_status["ready"] = True
    _storage_status["error"] = None

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
async def health() -> Dict[str, Any]:
    status = {
        "status": "ok" if _storage_status["ready"] else "degraded",
        "worker_enabled": settings.enable_worker,
        "worker_running": bool(_worker_thread and _worker_thread.is_alive()),
        "storage_backend": settings.storage_backend,
        "storage_ready": _storage_status["ready"],
        "storage_error": _storage_status["error"],
        "model_enabled": settings.model_enabled,
    }
    return status

@router.message(Command("health"))
async def health_telegram(message: Message):
    result = await health()
    if message.chat.id in chat_ids:
        await bot.send_message(chat_id=message.chat.id, text=str(result))
    else:
        await message.answer("No tienes permiso para usar este comando.")
    

@app.get("/health/sap")
def health_sap() -> Dict[str, Any]:
    try:
        return client.get_health()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/run/ingestion")
def run_ingestion() -> Dict[str, Any]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )
    try:
        return execute_ingestion_cycle()
    except Exception as exc:
        logger.exception("Manual ingestion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/run/reprocess-windows")
def run_reprocess_windows(limit: int = 50, persist: bool = True) -> Dict[str, Any]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )

    try:
        windows = store.get_recent_window_metrics(limit=limit)
        feature_history = store.get_recent_window_features(limit=settings.model_history_limit)
        processed = []

        for window_metrics in windows:
            current_window_key = str(window_metrics.get("window_key") or "")
            history_rows = [
                row
                for row in feature_history
                if str(row.get("window_key") or "") != current_window_key
            ]
            historical_signal = score_historical_pattern(
                current_metrics=window_metrics,
                history_rows=history_rows,
                min_history_rows=max(20, settings.model_min_training_rows),
            )
            model_signal = {
                "model_available": bool(window_metrics.get("model_available", False)),
                "is_anomaly": bool(window_metrics.get("is_anomaly", False)),
                "anomaly_score": float(window_metrics.get("anomaly_score", 0.0) or 0.0),
                "anomaly_percentile": float(window_metrics.get("anomaly_percentile", 0.0) or 0.0),
                "source": "historical_reprocess_existing_model_state",
            }
            raw_alerts, risk_summary = evaluate_window_risk(
                normalized_records=[],
                metrics=window_metrics,
                model_signal=model_signal,
                historical_signal=historical_signal,
                count_threshold=settings.error_security_threshold,
                attack_score_threshold=settings.attack_score_threshold,
            )
            updated_metrics = dict(window_metrics)
            updated_metrics.update(risk_summary)

            if persist:
                store.upsert_window_metrics(updated_metrics)

            processed.append(
                {
                    "window_key": current_window_key,
                    "total_records": updated_metrics.get("total_records", 0),
                    "threat_score": updated_metrics.get("threat_score", 0),
                    "detection_count": updated_metrics.get("detection_count", 0),
                    "attack_predicted": updated_metrics.get("attack_predicted", False),
                    "anomaly_reason": updated_metrics.get("anomaly_reason"),
                    "risk_level": updated_metrics.get("risk_level"),
                    "alert_types": [alert.get("alert_type") for alert in raw_alerts],
                }
            )

        return {
            "status": "ok",
            "persisted": persist,
            "processed_count": len(processed),
            "windows": processed,
        }
    except Exception as exc:
        logger.exception("Historical window reprocess failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/status/latest")
def status_latest() -> Dict[str, Any]:
    if not _storage_status["ready"]:
        return {
            "status": "degraded",
            "storage_backend": settings.storage_backend,
            "storage_ready": False,
            "storage_error": _storage_status["error"],
        }
    latest = store.get_last_run()
    if not latest:
        return {"status": "no-runs-yet"}
    return {
        "status": "ok",
        "latest_run": latest,
        "latest_window_metrics": store.get_latest_window_metrics(),
    }

@router.message(Command("last_status"))
async def last_status_telegram(message: Message):
    result =  status_latest()
    if message.chat.id in chat_ids:
        await bot.send_message(chat_id=message.chat.id, text=str(result))
    else:
        await message.answer("No tienes permiso para usar este comando.")


async def run() -> None:
    import uvicorn

    config = uvicorn.Config(app, host=settings.app_host, port=settings.app_port, reload=False)
    server = uvicorn.Server(config)

    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()       
    )


if __name__ == "__main__":
    run()
