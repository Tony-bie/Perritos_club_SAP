from __future__ import annotations

import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from fastapi import Response

from backend.core.config import load_settings
from backend.ml.retrain import retrain_model
from backend.services.chatbot import generate_chatbot_response
from backend.services.clients import SAPSOCClient
from backend.services.detection import (
    apply_baseline_shift_context,
    build_alert_submission_message,
    evaluate_window_risk,
    format_alert_events,
    score_historical_pattern,
    score_novelty_pattern,
    score_window_metrics,
    should_submit_alert_notification,
    unavailable_model_signal,
)
from backend.services.ingestion import (
    build_window_metric_batches,
    ingest_result_to_dict,
    normalize_records,
    run_ingestion_cycle,
)
from backend.storage import create_store
from backend.escalation.playbook import execute_playbook_for_alert

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

router = Router(name=__name__) if Router else None
dp = Dispatcher() if Dispatcher else None
if dp and router:
    dp.include_router(router)

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_recommended_rows() -> int:
    return max(20, settings.model_min_training_rows)


def _window_has_records(window: Dict[str, Any]) -> bool:
    try:
        return int(float(window.get("total_records", 0) or 0)) > 0
    except (TypeError, ValueError):
        return False


def _build_baseline_history_rows(
    preloaded_windows: list[Dict[str, Any]] | None = None,
    exclude_window_key: str | None = None,
) -> list[Dict[str, Any]]:
    windows = (
        preloaded_windows
        if preloaded_windows is not None
        else store.get_recent_window_metrics(limit=settings.model_history_limit)
    )
    return [
        window
        for window in windows
        if _window_has_records(window)
        and (not exclude_window_key or str(window.get("window_key") or "") != exclude_window_key)
    ]


def _build_history_status(
    baseline_rows: list[Dict[str, Any]] | None = None,
    model_feature_rows: list[Dict[str, Any]] | None = None,
    latest_window_metrics: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    baseline_history_rows = baseline_rows if baseline_rows is not None else _build_baseline_history_rows()
    feature_rows = model_feature_rows if model_feature_rows is not None else store.get_recent_window_features(
        limit=settings.model_history_limit
    )
    latest_metrics = latest_window_metrics if latest_window_metrics is not None else store.get_latest_window_metrics()
    historical_recommended_rows = _history_recommended_rows()
    model_recommended_rows = max(1, settings.model_min_training_rows)
    history_count = len(baseline_history_rows)
    model_history_count = len(feature_rows)
    historical_calibrated = history_count >= historical_recommended_rows
    model_calibrated = model_history_count >= model_recommended_rows
    latest_metrics = latest_metrics or {}

    return {
        "detection_active": True,
        "detection_status": "active",
        "training_required_for_detection": False,
        "calibration_note": (
            "La deteccion por reglas actuales esta activa desde la primera ventana. "
            "El historial y el modelo solo mejoran la calibracion de baseline/anomalias."
        ),
        "historical_calibrated": historical_calibrated,
        "historical_rows": history_count,
        "historical_recommended_rows": historical_recommended_rows,
        "historical_rows_to_calibration": max(0, historical_recommended_rows - history_count),
        "historical_source_table": "window_metrics",
        "model_calibrated": model_calibrated,
        "model_rows": model_history_count,
        "model_recommended_rows": model_recommended_rows,
        "model_rows_to_calibration": max(0, model_recommended_rows - model_history_count),
        "model_source_table": "window_features",
        "baseline_signal_status": "calibrated" if historical_calibrated else "warming_up",
        "model_signal_status": "calibrated" if model_calibrated else "warming_up",
        "current_rules_ready": True,
        "current_rules_note": (
            "Historial/modelo en warming_up solo limita baseline/anomaly ML; "
            "las reglas actuales de correlacion siguen evaluando cada ventana ingerida."
        ),
        "detection_mode": (
            "rules_baseline_model"
            if historical_calibrated and model_calibrated
            else "current_rules_with_limited_history"
        ),
        # Backward-compatible aliases. These are signal calibration flags, not
        # activation gates for detection.
        "historical_ready": historical_calibrated,
        "historical_min_required": historical_recommended_rows,
        "historical_rows_remaining": max(0, historical_recommended_rows - history_count),
        "model_ready": model_calibrated,
        "model_min_required": model_recommended_rows,
        "model_rows_remaining": max(0, model_recommended_rows - model_history_count),
        "history_limit": settings.model_history_limit,
        "latest_window_key": latest_metrics.get("window_key"),
        "latest_historical_source": latest_metrics.get("historical_source"),
        "latest_risk_level": latest_metrics.get("risk_level"),
        "latest_anomaly_reason": latest_metrics.get("anomaly_reason"),
        "latest_saved_at_utc": latest_metrics.get("saved_at_utc"),
    }


def _build_health_status() -> Dict[str, Any]:
    status = {
        "status": "ok" if _storage_status["ready"] else "degraded",
        "worker_enabled": settings.enable_worker,
        "worker_running": bool(_worker_thread and _worker_thread.is_alive()),
        "storage_backend": settings.storage_backend,
        "hana_configured": bool(settings.hana_host and settings.hana_user),
        "hana_schema": settings.hana_schema,
        "storage_ready": _storage_status["ready"],
        "storage_error": _storage_status["error"],
        "model_enabled": settings.model_enabled,
    }
    fallback_status = store.get_fallback_status()
    if fallback_status.get("enabled"):
        status["fallback"] = fallback_status
    return status


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
    metric_batches = build_window_metric_batches(
        normalized_records=normalized,
        window_start=ingest_result.window_start,
        window_end=ingest_result.window_end,
    )
    processed_windows = []
    alerts_inserted = 0
    alert_submissions = []
    latest_window_metrics: Dict[str, Any] = {}
    latest_model_signal: Dict[str, Any] = unavailable_model_signal("no_windows_processed")

    for window_metrics, window_records in metric_batches:
        window_metrics["run_id"] = run_id
        current_window_key = str(window_metrics.get("window_key") or "")
        store.bulk_upsert_window_metrics([window_metrics], batch_size=settings.batch_size)
        recent_windows_for_baseline = store.get_recent_window_metrics(limit=settings.model_history_limit)
        history_rows = _build_baseline_history_rows(
            preloaded_windows=recent_windows_for_baseline,
            exclude_window_key=current_window_key,
        )

        historical_signal = score_historical_pattern(
            current_metrics=window_metrics,
            history_rows=history_rows,
            min_history_rows=max(20, settings.model_min_training_rows),
        )
        novelty_signal = score_novelty_pattern(
            current_metrics=window_metrics,
            history_rows=history_rows,
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
            normalized_records=window_records,
            metrics=window_metrics,
            model_signal=model_signal,
            historical_signal=historical_signal,
            novelty_signal=novelty_signal,
            count_threshold=settings.error_security_threshold,
            attack_score_threshold=settings.attack_score_threshold,
        )
        recent_windows = store.get_recent_window_metrics(limit=12)
        raw_alerts, risk_summary = apply_baseline_shift_context(
            raw_alerts=raw_alerts,
            risk_summary=risk_summary,
            recent_window_metrics=recent_windows,
        )
        window_metrics.update(risk_summary)
        window_metrics["run_id"] = run_id
        store.bulk_upsert_window_metrics([window_metrics], batch_size=settings.batch_size)
        alert_events = format_alert_events(raw_alerts, run_id=run_id)
        window_alerts_inserted = store.insert_alerts(alert_events)
        alerts_inserted += window_alerts_inserted

        # Execute escalation playbook for each alert event to decide actions
        try:
            for alert_evt in alert_events:
                try:
                    execute_playbook_for_alert(alert=alert_evt, window_metrics=window_metrics, settings=settings, client=client, store=store)
                except Exception:
                    logger.exception("Failed to execute playbook for alert %s", alert_evt.get("alert_id"))
        except Exception:
            logger.exception("Playbook loop failed")

        submitted_alert_response: Dict[str, Any] | None = None
        submitted_alert_error: str | None = None
        submitted_alert_message: str | None = None
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
                    "Failed to submit alert to SAP endpoint. run_id=%s window_key=%s error=%s",
                    run_id,
                    current_window_key,
                    exc,
                )

        alert_submissions.append(
            {
                "window_key": current_window_key,
                "attempted": bool(raw_alerts),
                "eligible": submitted_alert_eligible,
                "eligibility_reason": submitted_alert_reason,
                "message": submitted_alert_message,
                "submitted": submitted_alert_response is not None,
                "response": submitted_alert_response,
                "error": submitted_alert_error,
            }
        )
        processed_windows.append(window_metrics)
        latest_window_metrics = window_metrics
        latest_model_signal = model_signal

    store.insert_ingest_run(run_data)
    latest_alert_submission = alert_submissions[-1] if alert_submissions else {
        "attempted": False,
        "eligible": False,
        "eligibility_reason": "no_windows_processed",
        "message": None,
        "submitted": False,
        "response": None,
        "error": None,
    }

    return {
        "run": run_data,
        "upserted_records": upserted,
        "alerts_count": alerts_inserted,
        "window_count": len(processed_windows),
        "alert_submission": latest_alert_submission,
        "alert_submissions": alert_submissions,
        "window_metrics": latest_window_metrics,
        "windows": processed_windows,
        "model": latest_model_signal,
        "history": _build_history_status(
            latest_window_metrics=latest_window_metrics,
        ),
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
            _maybe_run_retrain_job()
        except Exception as exc:
            logger.exception("Worker cycle failed: %s", exc)

        wait_seconds = max(1, settings.poll_interval_minutes * 60)
        _stop_event.wait(wait_seconds)

@app.get("/health")
async def health() -> Dict[str, Any]:
    return _build_health_status()

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


def _context_call(name: str, builder: Any) -> Dict[str, Any]:
    try:
        return {
            "ok": True,
            "data": builder(),
        }
    except Exception as exc:
        logger.warning("Failed to build chatbot endpoint context for %s: %s", name, exc)
        return {
            "ok": False,
            "error": str(exc),
        }
def _build_chatbot_context(question: str) -> Dict[str, Any]:
    recent_alerts = store.get_recent_alerts(limit=20)
    recent_windows = store.get_recent_window_metrics(limit=20)
    recent_runs = store.get_recent_ingest_runs(limit=10)
    latest_run = recent_runs[0] if recent_runs else {}
    latest_window = recent_windows[0] if recent_windows else {}
    fallback_status = store.get_fallback_status()

    high_alerts = sum(1 for alert in recent_alerts if str(alert.get("severity", "")).lower() in {"high", "critical"})
    anomaly_windows = sum(1 for window in recent_windows if bool(window.get("is_anomaly")))
    latest_status = latest_run.get("status", "no-runs") if latest_run else "no-runs"
    history_status_snapshot = _context_call("GET /history/status", _build_history_status)
    status_latest_snapshot = _context_call("GET /status/latest", status_latest)

    endpoint_snapshots = {
        "GET /health": _context_call("GET /health", _build_health_status),
        "GET /history/status": history_status_snapshot,
        "GET /status/latest": status_latest_snapshot,
        "GET /dashboard/summary?time_window_hours=24": _context_call(
            "GET /dashboard/summary?time_window_hours=24",
            lambda: dashboard_summary(time_window_hours=24),
        ),
        "GET /alerts/recent?limit=20": {
            "ok": True,
            "data": recent_alerts,
        },
        "GET /metrics/windows?limit=20": {
            "ok": True,
            "data": recent_windows,
        },
        "GET /runs/recent?limit=10": {
            "ok": True,
            "data": recent_runs,
        },
        "GET /health/sap": _context_call("GET /health/sap", health_sap),
    }

    return {
        "question": question,
        "context_generated_at_utc": _utc_now_iso(),
        "interpretation_contract": {
            "exact_history_gaps_require": "GET /history/status ok=true with *_rows_to_calibration fields",
            "insufficient_history_meaning": (
                "baseline/model anomaly calibration may be limited; current correlation rules still evaluate ingested windows"
            ),
            "forbidden_conclusions_without_current_evidence": [
                "risk is unknown only because history is insufficient",
                "no technical action is required",
                "the system is waiting for training activation",
                "the system is healthy without checking latest ingestion status",
            ],
        },
        "summary": {
            "recent_alerts": len(recent_alerts),
            "high_alerts": high_alerts,
            "anomaly_windows": anomaly_windows,
            "latest_run_status": latest_status,
            "latest_run_id": latest_run.get("run_id"),
            "latest_window_key": latest_window.get("window_key"),
            "latest_risk_level": latest_window.get("risk_level"),
            "latest_anomaly_reason": latest_window.get("anomaly_reason"),
            "fallback_enabled": bool(fallback_status.get("enabled")),
            "fallback_pending_counts": fallback_status.get("pending_counts", {}),
        },
        "endpoint_snapshots": endpoint_snapshots,
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
        processed = []

        for window_metrics in windows:
            current_window_key = str(window_metrics.get("window_key") or "")
            history_rows = _build_baseline_history_rows(
                preloaded_windows=windows,
                exclude_window_key=current_window_key,
            )[: settings.model_history_limit]
            historical_signal = score_historical_pattern(
                current_metrics=window_metrics,
                history_rows=history_rows,
                min_history_rows=max(20, settings.model_min_training_rows),
            )
            novelty_signal = score_novelty_pattern(
                current_metrics=window_metrics,
                history_rows=history_rows,
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
                novelty_signal=novelty_signal,
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


@app.post("/run/rebuild-windows-from-raw")
def run_rebuild_windows_from_raw(
    limit: int = 0,
    persist: bool = True,
    _: None = Depends(_require_admin_token),
) -> Dict[str, Any]:
    if not _storage_status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Storage backend unavailable: {_storage_status['error'] or 'unknown error'}",
        )

    try:
        effective_limit = 100_000 if int(limit) <= 0 else int(limit)
        raw_logs = store.export_raw_logs(limit=effective_limit)
        normalized = normalize_records(raw_logs)
        metric_batches = build_window_metric_batches(
            normalized_records=normalized,
            window_start=None,
            window_end=None,
        )
        processed = []

        for window_metrics, window_records in metric_batches:
            current_window_key = str(window_metrics.get("window_key") or "")
            if persist:
                store.upsert_window_metrics(window_metrics)

            recent_windows_for_baseline = store.get_recent_window_metrics(limit=settings.model_history_limit)
            history_rows = _build_baseline_history_rows(
                preloaded_windows=recent_windows_for_baseline,
                exclude_window_key=current_window_key,
            )
            historical_signal = score_historical_pattern(
                current_metrics=window_metrics,
                history_rows=history_rows,
                min_history_rows=max(20, settings.model_min_training_rows),
            )
            novelty_signal = score_novelty_pattern(
                current_metrics=window_metrics,
                history_rows=history_rows,
            )
            model_signal = unavailable_model_signal("raw_rebuild_model_skipped")
            raw_alerts, risk_summary = evaluate_window_risk(
                normalized_records=window_records,
                metrics=window_metrics,
                model_signal=model_signal,
                historical_signal=historical_signal,
                novelty_signal=novelty_signal,
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
                    "risk_level": updated_metrics.get("risk_level"),
                    "anomaly_reason": updated_metrics.get("anomaly_reason"),
                    "historical_source": updated_metrics.get("historical_source"),
                    "alert_types": [alert.get("alert_type") for alert in raw_alerts],
                }
            )

        return {
            "status": "ok",
            "persisted": persist,
            "raw_logs_read": len(raw_logs),
            "window_count": len(processed),
            "history": _build_history_status(),
            "windows": processed,
        }
    except Exception as exc:
        logger.exception("Raw log window rebuild failed: %s", exc)
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


@app.get("/history/status")
def history_status() -> Dict[str, Any]:
    if not _storage_status["ready"]:
        return {
            "status": "degraded",
            "storage_backend": settings.storage_backend,
            "storage_ready": False,
            "storage_error": _storage_status["error"],
        }

    response = {
        "status": "ok",
        "storage_backend": settings.storage_backend,
        **_build_history_status(),
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
    from backend.telegram import run_bot 

    config = uvicorn.Config(app, host=settings.app_host, port=settings.app_port, reload=False)
    server = uvicorn.Server(config)

    tasks = [server.serve()]
    tasks.append(run_bot())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(run())
