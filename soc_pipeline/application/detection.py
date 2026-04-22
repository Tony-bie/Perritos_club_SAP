from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from soc_pipeline.domain.constants import SEVERITY_WEIGHTS


def detect_threats(
    metrics: dict[str, Any],
    alert_threshold: int,
    ml_signal: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    detections: list[dict[str, Any]] = []

    def add_detection(rule_name: str, severity: str, message: str, context: dict[str, Any]) -> None:
        detections.append(
            {
                "detection_id": uuid.uuid4().hex,
                "window_key": metrics["window_key"],
                "rule_name": rule_name,
                "severity": severity,
                "score": SEVERITY_WEIGHTS[severity],
                "message": message,
                "context": context,
                "detected_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    ml_signal = ml_signal or default_ml_signal()

    if metrics["security_count"] >= max(5, int(metrics["baseline_security_count"] * 2) if metrics["baseline_security_count"] else 5):
        add_detection(
            "security_event_spike",
            "critical",
            "Security events spiked in the current 30-minute window.",
            {
                "security_count": metrics["security_count"],
                "baseline_security_count": metrics["baseline_security_count"],
            },
        )

    if metrics["error_count"] >= 10 and metrics["system_error_rate"] >= 0.25:
        add_detection(
            "system_error_spike",
            "high",
            "System logs show an elevated error rate.",
            {
                "error_count": metrics["error_count"],
                "system_error_rate": metrics["system_error_rate"],
                "baseline_system_error_rate": metrics["baseline_system_error_rate"],
            },
        )

    if metrics["http_5xx_count"] >= 8:
        add_detection(
            "server_failure_pattern",
            "medium",
            "5xx responses crossed the investigation threshold.",
            {
                "http_5xx_count": metrics["http_5xx_count"],
                "baseline_http_5xx_count": metrics["baseline_http_5xx_count"],
            },
        )

    if metrics["max_events_from_single_ip"] >= 25 or metrics["max_services_from_single_ip"] >= 8:
        add_detection(
            "ip_concentration",
            "high",
            "One client IP is dominating the window and touching many services.",
            {
                "max_events_from_single_ip": metrics["max_events_from_single_ip"],
                "max_services_from_single_ip": metrics["max_services_from_single_ip"],
                "baseline_max_events_from_single_ip": metrics["baseline_max_events_from_single_ip"],
            },
        )

    if metrics["suspicious_ip_count"] >= 3:
        add_detection(
            "multi_ip_pressure",
            "medium",
            "Several IPs crossed the per-window activity threshold.",
            {"suspicious_ip_count": metrics["suspicious_ip_count"]},
        )

    if metrics["llm_timeout_count"] >= 5 and metrics["llm_timeout_rate"] >= 0.20:
        add_detection(
            "llm_timeout_spike",
            "high",
            "LLM timeout rate indicates abnormal model or prompt traffic.",
            {
                "llm_timeout_count": metrics["llm_timeout_count"],
                "llm_timeout_rate": metrics["llm_timeout_rate"],
                "baseline_llm_timeout_rate": metrics["baseline_llm_timeout_rate"],
            },
        )

    if metrics["avg_llm_latency_ms"] >= max(4000.0, metrics["baseline_avg_llm_latency_ms"] * 1.8 if metrics["baseline_avg_llm_latency_ms"] else 4000.0):
        add_detection(
            "llm_latency_spike",
            "medium",
            "LLM latency is materially above the operating baseline.",
            {
                "avg_llm_latency_ms": metrics["avg_llm_latency_ms"],
                "p95_llm_latency_ms": metrics["p95_llm_latency_ms"],
                "baseline_avg_llm_latency_ms": metrics["baseline_avg_llm_latency_ms"],
            },
        )

    if metrics["total_llm_cost_usd"] >= max(15.0, metrics["baseline_total_llm_cost_usd"] * 2.5 if metrics["baseline_total_llm_cost_usd"] else 15.0):
        add_detection(
            "llm_cost_spike",
            "medium",
            "LLM cost increased sharply in this batch.",
            {
                "total_llm_cost_usd": metrics["total_llm_cost_usd"],
                "baseline_total_llm_cost_usd": metrics["baseline_total_llm_cost_usd"],
            },
        )

    if ml_signal["model_available"] and ml_signal["is_anomaly"]:
        severity = "critical" if ml_signal["confidence_score"] >= 90 else "high"
        add_detection(
            "ml_window_anomaly",
            severity,
            "The hana-ml model marked this 30-minute window as anomalous.",
            {
                "ml_anomaly_score": ml_signal["anomaly_score"],
                "ml_confidence_score": ml_signal["confidence_score"],
                "training_row_count": ml_signal["training_row_count"],
                "source": ml_signal["source"],
            },
        )

    if len(detections) >= 2:
        add_detection(
            "multi_signal_correlation",
            "high",
            "Multiple independent signals fired in the same window.",
            {"triggered_rules": [detection["rule_name"] for detection in detections]},
        )

    rule_score = min(sum(detection["score"] for detection in detections), 100)
    ml_weighted_score = 0
    if ml_signal["model_available"]:
        ml_weighted_score = int(round(ml_signal["confidence_score"] * 0.6))
    final_score = min(max(rule_score, ml_weighted_score, rule_score + int(round(ml_signal["confidence_score"] * 0.25))), 100)
    attack_predicted = final_score >= alert_threshold or any(
        detection["severity"] == "critical" for detection in detections
    )
    if ml_signal["model_available"] and ml_signal["is_anomaly"] and ml_signal["confidence_score"] >= 80:
        attack_predicted = True

    decision_source = "rules_only"
    if ml_signal["model_available"] and detections:
        decision_source = "rules_and_ml"
    elif ml_signal["model_available"]:
        decision_source = "ml_only"

    detection_summary = {
        "rule_score": rule_score,
        "threat_score": final_score,
        "final_score": final_score,
        "detection_count": len(detections),
        "attack_predicted": attack_predicted,
        "alert_threshold": alert_threshold,
        "decision_source": decision_source,
        "ml_model_available": ml_signal["model_available"],
        "ml_training_row_count": ml_signal["training_row_count"],
        "ml_anomaly_score": ml_signal["anomaly_score"],
        "ml_confidence_score": ml_signal["confidence_score"],
        "ml_is_anomaly": ml_signal["is_anomaly"],
        "ml_source": ml_signal["source"],
    }
    return detections, detection_summary


def default_ml_signal() -> dict[str, Any]:
    return {
        "model_available": False,
        "training_row_count": 0,
        "anomaly_score": 0.0,
        "confidence_score": 0.0,
        "is_anomaly": False,
        "source": "not_available",
    }
