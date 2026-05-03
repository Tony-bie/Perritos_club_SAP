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
    total_records = int(metrics.get("total_records", len(normalized_records)) or 0)

    if total_records <= 0:
        summary = {
            "threat_score": 0,
            "attack_predicted": False,
            "detection_count": 0,
            "risk_level": "no_data",
            "anomaly_reason": "empty_window",
            "historical_available": bool(historical_signal.get("historical_available", False)),
            "historical_source": historical_signal.get("historical_source", "unavailable"),
            "pattern_score": 0.0,
            "max_feature_deviation": 0.0,
            "pattern_signals": [],
            "model_available": bool(model_signal.get("model_available", False)),
            "anomaly_score": 0.0,
            "anomaly_percentile": 0.0,
            "is_anomaly": False,
            "model_source": model_signal.get("source", "unavailable"),
            "records_evaluated": len(normalized_records),
            "window_key": metrics.get("window_key"),
        }
        return alerts, summary

    pattern_status = str(historical_signal.get("pattern_status", "unknown"))
    pattern_reason = str(historical_signal.get("pattern_reason", "unknown"))

    if pattern_reason == "possible_incomplete_window":
        max_feature_deviation = float(historical_signal.get("max_feature_deviation", 0.0) or 0.0)
        severity = "high" if max_feature_deviation >= 8.0 else "medium"
        score = 20 if severity == "high" else 10
        alerts.append(
            _alert(
                "data_quality_or_availability_drop",
                severity,
                score,
                {
                    "reason": pattern_reason,
                    "total_records": total_records,
                    "max_feature_deviation": max_feature_deviation,
                    "top_signals": historical_signal.get("pattern_signals", [])[:3],
                },
            )
        )
        summary = {
            "threat_score": score,
            "attack_predicted": False,
            "detection_count": len(alerts),
            "risk_level": "data_quality",
            "anomaly_reason": pattern_reason,
            "historical_available": bool(historical_signal.get("historical_available", False)),
            "historical_source": historical_signal.get("historical_source", "unavailable"),
            "pattern_score": float(historical_signal.get("pattern_score", 0.0) or 0.0),
            "max_feature_deviation": max_feature_deviation,
            "pattern_signals": historical_signal.get("pattern_signals", []),
            "model_available": bool(model_signal.get("model_available", False)),
            "anomaly_score": 0.0,
            "anomaly_percentile": 0.0,
            "is_anomaly": False,
            "model_source": model_signal.get("source", "unavailable"),
            "records_evaluated": len(normalized_records),
            "window_key": metrics.get("window_key"),
        }
        return alerts, summary

    if pattern_reason in {"llm_activity_drop", "system_activity_drop"}:
        max_feature_deviation = float(historical_signal.get("max_feature_deviation", 0.0) or 0.0)
        severity = "high" if max_feature_deviation >= 8.0 else "medium"
        score = 20 if severity == "high" else 10
        alerts.append(
            _alert(
                pattern_reason,
                severity,
                score,
                {
                    "reason": pattern_reason,
                    "total_records": total_records,
                    "max_feature_deviation": max_feature_deviation,
                    "top_signals": historical_signal.get("pattern_signals", [])[:3],
                },
            )
        )
    else:
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

    alerts.extend(_security_combination_alerts(metrics, count_threshold, pattern_reason))
    has_security_combination = _has_security_combination_alert(alerts)

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

    attack_predicted = (
        pattern_reason == "possible_attack_pattern"
        and pattern_status in {"suspicious", "high_anomaly", "critical_anomaly"}
        and threat_score >= int(attack_score_threshold)
    )

    if has_security_combination and threat_score >= int(attack_score_threshold):
        attack_predicted = True

    # Model anomaly reinforces suspicious/high windows, but should not override
    # explicit signs of incomplete ingestion.
    if (
        model_available
        and is_model_anomaly
        and pattern_reason in {"possible_attack_pattern", "upward_pattern_break"}
        and threat_score >= max(50, int(attack_score_threshold) - 15)
    ):
        attack_predicted = True

    summary_reason = pattern_reason
    summary_risk_level = pattern_status
    if has_security_combination and pattern_reason in {"unknown", "insufficient_history", "general_pattern_break"}:
        summary_reason = "security_correlation"
    if pattern_reason in {"llm_activity_drop", "system_activity_drop"}:
        summary_risk_level = "service_activity_anomaly"
    if has_security_combination and pattern_status in {"unknown", "normal"}:
        summary_risk_level = "security_correlation"

    summary = {
        "threat_score": threat_score,
        "attack_predicted": attack_predicted,
        "detection_count": len(alerts),
        "risk_level": summary_risk_level,
        "anomaly_reason": summary_reason,
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


def _security_combination_alerts(
    metrics: Dict[str, Any],
    count_threshold: int,
    pattern_reason: str,
) -> List[Dict[str, Any]]:
    security_count = _as_int(metrics.get("security_count"))
    error_count = _as_int(metrics.get("error_count"))
    http_4xx_count = _as_int(metrics.get("http_4xx_count"))
    http_5xx_count = _as_int(metrics.get("http_5xx_count"))
    llm_error_count = _as_int(metrics.get("llm_error_count"))
    llm_timeout_count = _as_int(metrics.get("llm_timeout_count"))
    max_events_from_single_ip = _as_int(metrics.get("max_events_from_single_ip"))
    top_ip_event_share = _as_float(metrics.get("top_ip_event_share"))
    security_event_rate = _as_float(metrics.get("security_event_rate"))
    system_error_rate = _as_float(metrics.get("system_error_rate"))
    threshold = max(1, int(count_threshold))
    alerts: List[Dict[str, Any]] = []

    security_rate_elevated = security_event_rate >= 0.04
    security_volume_elevated = security_count >= threshold * 3 and security_event_rate >= 0.035
    security_single_ip_elevated = max_events_from_single_ip >= threshold and top_ip_event_share >= 0.25
    historical_attack_context = pattern_reason == "possible_attack_pattern"
    has_security_context = (
        security_rate_elevated
        or security_volume_elevated
        or security_single_ip_elevated
        or historical_attack_context
    )

    if not has_security_context:
        return alerts

    if security_count >= threshold and error_count >= threshold and (
        security_rate_elevated or security_volume_elevated or historical_attack_context
    ):
        severity = "critical" if security_event_rate >= 0.05 and system_error_rate >= 0.15 else "high"
        score = 30 if severity == "critical" else 22
        alerts.append(
            _alert(
                "security_error_correlation",
                severity,
                score,
                {
                    "security_count": security_count,
                    "error_count": error_count,
                    "security_event_rate": security_event_rate,
                    "system_error_rate": system_error_rate,
                },
            )
        )

    http_failure_count = http_4xx_count + http_5xx_count
    if security_count >= threshold and http_failure_count >= threshold and (
        security_rate_elevated or security_single_ip_elevated or historical_attack_context
    ):
        severity = "critical" if http_5xx_count >= threshold else "high"
        score = 28 if severity == "critical" else 20
        alerts.append(
            _alert(
                "security_http_failure_correlation",
                severity,
                score,
                {
                    "security_count": security_count,
                    "http_4xx_count": http_4xx_count,
                    "http_5xx_count": http_5xx_count,
                    "http_failure_count": http_failure_count,
                },
            )
        )

    if security_count >= threshold and max_events_from_single_ip >= threshold and top_ip_event_share >= 0.25:
        alerts.append(
            _alert(
                "security_single_ip_pressure",
                "high",
                20,
                {
                    "security_count": security_count,
                    "max_events_from_single_ip": max_events_from_single_ip,
                    "top_ip_event_share": top_ip_event_share,
                },
            )
        )

    llm_failure_count = llm_error_count + llm_timeout_count
    if security_count >= threshold and llm_failure_count >= threshold and (
        pattern_reason == "llm_activity_drop"
        or security_rate_elevated
        or historical_attack_context
    ):
        alerts.append(
            _alert(
                "security_llm_disruption_correlation",
                "high",
                20,
                {
                    "security_count": security_count,
                    "llm_error_count": llm_error_count,
                    "llm_timeout_count": llm_timeout_count,
                    "llm_failure_count": llm_failure_count,
                },
            )
        )

    return alerts


def _has_security_combination_alert(alerts: List[Dict[str, Any]]) -> bool:
    return any(str(alert.get("alert_type", "")).startswith("SECURITY_") for alert in alerts)


def _as_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
