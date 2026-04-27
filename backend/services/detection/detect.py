from __future__ import annotations

from typing import Any, Dict, List


def evaluate_window_risk(
    normalized_records: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    model_signal: Dict[str, Any],
    historical_signal: Dict[str, Any],
    count_threshold: int = 25,
    attack_score_threshold: int = 70,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:

    alerts: List[Dict[str, Any]] = []

    for signal in historical_signal.get("pattern_signals", []):
        alerts.append(
            _alert(
                f"historical_{signal.get('feature', 'unknown')}",
                str(signal.get("severity", "medium")),
                int(signal.get("points", 0) or 0),
                {
                    "feature": signal.get("feature"),
                    "value": signal.get("value"),
                    "median": signal.get("median"),
                    "mad": signal.get("mad"),
                    "robust_z": signal.get("robust_z"),
                    "abs_robust_z": signal.get("abs_robust_z"),
                    "direction": signal.get("direction"),
                },
            )
        )

    model_available = bool(model_signal.get("model_available"))
    is_model_anomaly = bool(model_signal.get("is_anomaly", False))
    anomaly_percentile = float(model_signal.get("anomaly_percentile", 0.0) or 0.0)

    if model_available and is_model_anomaly:
        alerts.append(
            _alert(
                "anomaly_model_trigger",
                "high",
                max(15, min(35, int(anomaly_percentile // 3))),
                {
                    "anomaly_score": model_signal.get("anomaly_score", 0.0),
                    "anomaly_percentile": anomaly_percentile,
                    "training_row_count": model_signal.get("training_row_count", 0),
                },
            )
        )

    threat_score = min(100, sum(int(alert["score"]) for alert in alerts))

    pattern_status = str(historical_signal.get("pattern_status", "unknown"))
    pattern_reason = str(historical_signal.get("pattern_reason", "unknown"))

    attack_predicted = (
        pattern_reason == "possible_attack_pattern"
        and pattern_status in {"suspicious", "high_anomaly", "critical_anomaly"}
        and threat_score >= int(attack_score_threshold)
    )

    # Model anomaly reinforces suspicious/high windows, but should not override
    # explicit signs of incomplete ingestion.
    if (
        model_available
        and is_model_anomaly
        and pattern_reason in {"possible_attack_pattern", "upward_pattern_break"}
        and threat_score >= max(50, int(attack_score_threshold) - 15)
    ):
        attack_predicted = True

    if pattern_reason == "possible_incomplete_window":
        attack_predicted = False

    summary = {
        "threat_score": threat_score,
        "attack_predicted": attack_predicted,
        "detection_count": len(alerts),
        "risk_level": pattern_status,
        "anomaly_reason": pattern_reason,
        "historical_available": bool(historical_signal.get("historical_available", False)),
        "historical_source": historical_signal.get("historical_source", "unavailable"),
        "pattern_score": float(historical_signal.get("pattern_score", 0.0) or 0.0),
        "max_feature_deviation": float(historical_signal.get("max_feature_deviation", 0.0) or 0.0),
        "pattern_signals": historical_signal.get("pattern_signals", []),
        "model_available": model_available,
        "anomaly_score": float(model_signal.get("anomaly_score", 0.0) or 0.0),
        "anomaly_percentile": anomaly_percentile,
        "is_anomaly": is_model_anomaly,
        "model_source": model_signal.get("source", "unavailable"),
        "records_evaluated": len(normalized_records),
        "window_key": metrics.get("window_key"),
    }
    return alerts, summary


def _alert(alert_type: str, severity: str, score: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "alert_type": str(alert_type).upper(),
        "severity": severity,
        "score": int(score),
        "payload": payload,
    }
