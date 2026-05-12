from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from backend.core.config import load_settings
from backend.services.chatbot import generate_chatbot_response
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

try:
    from aiogram import Bot, Dispatcher, Router
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.filters import Command
    from aiogram.types import Message
except ModuleNotFoundError:
    Bot = None
    Dispatcher = None
    Router = None
    DefaultBotProperties = None
    ParseMode = None
    Command = None
    Message = Any

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
bot: Bot | None = None
if Bot and DefaultBotProperties and ParseMode and token:
    try:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    except Exception as exc:
        logger.warning("Telegram bot disabled due to invalid token: %s", exc)
else:
    logger.info("Telegram bot disabled: TOKEN_BOT_TELEGRAM is not configured")

app = FastAPI(title="SAP SOC Backend", version="0.1.0")
_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None
_storage_status: Dict[str, Any] = {
    "ready": False,
    "error": None,
}

router = Router(name=__name__) if Router else None
dp = Dispatcher() if Dispatcher else None
if dp and router:
    dp.include_router(router)

class CleanupRequest(BaseModel):
    retention_days: int = 90


class RecentWindowMetricResponse(BaseModel):
    window_key: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    total_records: int | None = None
    threat_score: int | None = None
    attack_predicted: bool | None = None
    model_available: bool | None = None
    is_anomaly: bool | None = None
    anomaly_score: float | None = None
    anomaly_percentile: float | None = None
    saved_at_utc: str | None = None


class RecentAlertResponse(BaseModel):
    alert_id: str | None = None
    run_id: str | None = None
    detected_at_utc: str | None = None
    alert_type: str | None = None
    severity: str | None = None
    payload: Dict[str, Any] | None = None


class RecentIngestRunResponse(BaseModel):
    run_id: str | None = None
    status: str | None = None
    started_at_utc: str | None = None
    ended_at_utc: str | None = None
    duration_seconds: float | None = None
    window_start: str | None = None
    window_end: str | None = None
    total_pages_expected: int | None = None
    total_pages_fetched: int | None = None
    total_records_info: int | None = None
    total_records_fetched: int | None = None
    error_message: str | None = None


class DashboardSummaryResponse(BaseModel):
    total_alerts: int
    alerts_by_severity: Dict[str, int]
    top_metrics: Dict[str, Any]
    last_run: Dict[str, Any]
    generated_at: str


def _require_admin_token(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    expected_token = settings.admin_api_key or settings.sap_soc_token
    if not expected_token:
        raise HTTPException(status_code=503, detail="Admin auth is not configured")

    provided_token = ""
    if authorization and authorization.startswith("Bearer "):
        provided_token = authorization.removeprefix("Bearer ").strip()
    elif x_api_key:
        provided_token = x_api_key.strip()

    if provided_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")


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
    upserted = store.bulk_upsert_raw_logs(normalized, batch_size=settings.batch_size)
    window_metrics = build_window_metrics(
        normalized_records=normalized,
        window_start=ingest_result.window_start,
        window_end=ingest_result.window_end,
    )
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
    store.bulk_upsert_window_metrics([window_metrics], batch_size=settings.batch_size)
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
    fallback_status = store.get_fallback_status()
    if fallback_status.get("enabled"):
        status["fallback"] = fallback_status
    return status

def _format_kv_for_telegram(title: str, data: Dict[str, Any]) -> str:
    lines = [title]
    for key, value in data.items():
        key_text = key.replace("_", " ").title()
        value_text = str(value)
        lines.append(f"- {key_text}: {value_text}")
    return "\n".join(lines)


def _extract_command_argument(raw_text: str, command_name: str) -> str:
    pattern = rf"^/{command_name}(?:@[\w_]+)?\s*(.*)$"
    match = re.match(pattern, raw_text.strip(), flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip()


def _build_chatbot_context(question: str) -> Dict[str, Any]:
    recent_alerts = store.get_recent_alerts(limit=8)
    recent_windows = store.get_recent_window_metrics(limit=6)
    recent_runs = store.get_recent_ingest_runs(limit=3)

    high_alerts = sum(1 for alert in recent_alerts if str(alert.get("severity", "")).lower() in {"high", "critical"})
    anomaly_windows = sum(1 for window in recent_windows if bool(window.get("is_anomaly")))
    latest_status = recent_runs[0].get("status", "no-runs") if recent_runs else "no-runs"

    return {
        "question": question,
        "summary": {
            "recent_alerts": len(recent_alerts),
            "high_alerts": high_alerts,
            "anomaly_windows": anomaly_windows,
            "latest_run_status": latest_status,
        },
        "recent_alerts": recent_alerts,
        "recent_windows": recent_windows,
        "recent_runs": recent_runs,
    }


async def _handle_telegram_analysis(message: Message, question: str) -> None:
    if not settings.telegram_chatbot_enabled:
        await message.answer("El chatbot esta deshabilitado. Activa TELEGRAM_CHATBOT_ENABLED=true.")
        return

    if not _storage_status["ready"]:
        await message.answer(
            f"No puedo consultar logs ahora. Storage no disponible: {_storage_status['error'] or 'unknown error'}"
        )
        return

    if not question:
        await message.answer("Uso: /ask <pregunta>. Ejemplo: /ask que esta pasando con los logs?")
        return

    context = _build_chatbot_context(question=question)
    response = generate_chatbot_response(question=question, context=context, settings=settings)
    text = str(response.get("text") or "No hubo respuesta")
    source = str(response.get("source") or "unknown")
    await message.answer(f"{text}\n\nFuente: {source}", parse_mode=None)


if router and Command:
    @router.message(Command("start"))
    async def start_telegram(message: Message) -> None:
        await message.answer(
            "Comandos disponibles:\n"
            "/health - estado general\n"
            "/last_status - ultimo run\n"
            "/ask <pregunta> - interpreta alertas y logs recientes"
        )

    @router.message(Command("health"))
    async def health_telegram(message: Message) -> None:
        result = await health()
        await message.answer(_format_kv_for_telegram("Estado del sistema", result), parse_mode=None)


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
        effective_limit = 1_000_000 if int(limit) <= 0 else int(limit)
        windows = store.get_recent_window_metrics(limit=effective_limit)
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
            model_available = bool(window_metrics.get("model_available", False))
            model_signal = {
                "model_available": model_available,
                "is_anomaly": bool(
                    window_metrics.get(
                        "model_is_anomaly",
                        window_metrics.get("is_anomaly", False) if model_available else False,
                    )
                ),
                "anomaly_score": float(
                    window_metrics.get(
                        "model_anomaly_score",
                        window_metrics.get("anomaly_score", 0.0) if model_available else 0.0,
                    )
                    or 0.0
                ),
                "anomaly_percentile": float(
                    window_metrics.get(
                        "model_anomaly_percentile",
                        window_metrics.get("anomaly_percentile", 0.0) if model_available else 0.0,
                    )
                    or 0.0
                ),
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
                    "is_anomaly": updated_metrics.get("is_anomaly", False),
                    "anomaly_score": updated_metrics.get("anomaly_score", 0.0),
                    "anomaly_percentile": updated_metrics.get("anomaly_percentile", 0.0),
                    "attack_predicted": updated_metrics.get("attack_predicted", False),
                    "anomaly_reason": updated_metrics.get("anomaly_reason"),
                    "risk_level": updated_metrics.get("risk_level"),
                    "alert_types": [alert.get("alert_type") for alert in raw_alerts],
                }
            )

        return {
            "status": "ok",
            "persisted": persist,
            "requested_limit": limit,
            "effective_limit": effective_limit,
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
    response = {
        "status": "ok",
        "latest_run": latest,
        "latest_window_metrics": store.get_latest_window_metrics(),
    }
    fallback_status = store.get_fallback_status()
    if fallback_status.get("enabled"):
        response["fallback"] = fallback_status
    return response


@app.post("/run/resync-fallback")
def run_resync_fallback(_: None = Depends(_require_admin_token)) -> Dict[str, Any]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )

    fallback_status = store.get_fallback_status()
    if not fallback_status.get("enabled"):
        return {
            "status": "not_enabled",
            "message": "Fallback sync is only available when HANA uses SQLite fallback storage.",
        }

    try:
        return store.sync_fallback_to_primary()
    except Exception as exc:
        logger.exception("Fallback resync failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

if router and Command:
    @router.message(Command("last_status"))
    async def last_status_telegram(message: Message) -> None:
        result = status_latest()
        await message.answer(_format_kv_for_telegram("Ultimo estado", result), parse_mode=None)

    @router.message(Command("ask"))
    async def ask_telegram(message: Message) -> None:
        raw_text = (message.text or "").strip()
        question = _extract_command_argument(raw_text, "ask")
        await _handle_telegram_analysis(message, question)

    @router.message()
    async def free_text_telegram(message: Message) -> None:
        raw_text = (message.text or "").strip()
        if not raw_text or raw_text.startswith("/"):
            return
        await _handle_telegram_analysis(message, raw_text)


@app.get("/alerts/recent", response_model=list[RecentAlertResponse])
def alerts_recent(limit: int = Query(default=50, ge=1, le=200)) -> list[Dict[str, Any]]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )
    return store.get_recent_alerts(limit=limit)


@app.get("/metrics/windows", response_model=list[RecentWindowMetricResponse])
def metrics_windows(limit: int = Query(default=50, ge=1, le=200)) -> list[Dict[str, Any]]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )
    return store.get_recent_window_metrics(limit=limit)


@app.get("/runs/recent", response_model=list[RecentIngestRunResponse])
def runs_recent(limit: int = Query(default=20, ge=1, le=200)) -> list[Dict[str, Any]]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )
    return store.get_recent_ingest_runs(limit=limit)


@app.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(time_window_hours: int = Query(default=24, ge=1, le=720)) -> Dict[str, Any]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )
    return store.get_dashboard_summary(time_window_hours=time_window_hours)


@app.post("/api/admin/cleanup")
def admin_cleanup(
    payload: CleanupRequest,
    _: None = Depends(_require_admin_token),
) -> Dict[str, Any]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )

    try:
        return store.call_cleanup_procedure(retention_days=payload.retention_days)
    except Exception as exc:
        logger.exception("Cleanup failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


async def run() -> None:
    import uvicorn

    config = uvicorn.Config(app, host=settings.app_host, port=settings.app_port, reload=False)
    server = uvicorn.Server(config)

    tasks = [server.serve()]
    if dp is not None and bot is not None:
        tasks.append(dp.start_polling(bot))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(run())
