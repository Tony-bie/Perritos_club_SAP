from __future__ import annotations

from typing import Any, Dict, List


def evaluate_window_risk(
    normalized_records: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    model_signal: Dict[str, Any],
    count_threshold: int = 25,
    attack_score_threshold: int = 40,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []

    if metrics.get("security_count", 0) >= count_threshold:
        alerts.append(
            _alert(
                "security_event_spike",
                "critical",
                35,
                {
                    "security_count": metrics.get("security_count", 0),
                    "threshold": count_threshold,
                },
            )
        )

    if metrics.get("http_5xx_count", 0) >= max(10, int(metrics.get("total_records", 0) * 0.03)):
        alerts.append(
            _alert(
                "server_failure_pattern",
                "medium",
                12,
                {"http_5xx_count": metrics.get("http_5xx_count", 0)},
            )
        )

    if metrics.get("max_events_from_single_ip", 0) >= max(25, int(metrics.get("system_log_count", 0) * 0.2)):
        alerts.append(
            _alert(
                "ip_concentration",
                "high",
                18,
                {
                    "max_events_from_single_ip": metrics.get("max_events_from_single_ip", 0),
                    "top_ip_event_share": metrics.get("top_ip_event_share", 0.0),
                },
            )
        )

    if metrics.get("unique_client_ips", 0) >= 20 and metrics.get("security_count", 0) > 0:
        alerts.append(
            _alert(
                "multi_ip_pressure",
                "medium",
                10,
                {"unique_client_ips": metrics.get("unique_client_ips", 0)},
            )
        )

    if metrics.get("avg_llm_latency_ms", 0.0) >= 2500 or metrics.get("llm_timeout_rate", 0.0) >= 0.15:
        alerts.append(
            _alert(
                "llm_latency_spike",
                "medium",
                10,
                {
                    "avg_llm_latency_ms": metrics.get("avg_llm_latency_ms", 0.0),
                    "llm_timeout_rate": metrics.get("llm_timeout_rate", 0.0),
                },
            )
        )

    if model_signal.get("model_available") and model_signal.get("is_anomaly"):
        percentile = float(model_signal.get("anomaly_percentile", 0.0))
        alerts.append(
            _alert(
                "anomaly_model_trigger",
                "high",
                max(15, min(35, int(percentile // 3))),
                {
                    "anomaly_score": model_signal.get("anomaly_score", 0.0),
                    "anomaly_percentile": percentile,
                    "training_row_count": model_signal.get("training_row_count", 0),
                },
            )
        )

    threat_score = min(100, sum(int(alert["score"]) for alert in alerts))
    attack_predicted = threat_score >= attack_score_threshold

    return alerts, {
        "threat_score": threat_score,
        "attack_predicted": attack_predicted,
        "detection_count": len(alerts),
        "model_available": bool(model_signal.get("model_available")),
        "anomaly_score": float(model_signal.get("anomaly_score", 0.0)),
        "anomaly_percentile": float(model_signal.get("anomaly_percentile", 0.0)),
        "is_anomaly": bool(model_signal.get("is_anomaly", False)),
        "model_source": model_signal.get("source", "unavailable"),
        "records_evaluated": len(normalized_records),
    }


def _alert(alert_type: str, severity: str, score: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "alert_type": alert_type.upper(),
        "severity": severity,
        "score": int(score),
        "payload": payload,
    }
