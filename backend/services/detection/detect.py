from __future__ import annotations

from typing import Any, Dict, List


BASELINE_SHIFT_REASONS = {"llm_activity_drop", "baseline_shift_candidate"}
ANOMALOUS_PATTERN_STATUSES = {"suspicious", "high_anomaly", "critical_anomaly"}
def evaluate_window_risk(
    normalized_records: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    model_signal: Dict[str, Any],
    historical_signal: Dict[str, Any],
    novelty_signal: Dict[str, Any] | None = None,
    count_threshold: int = 25,
    attack_score_threshold: int = 70,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:

    alerts: List[Dict[str, Any]] = []
    novelty_signal = novelty_signal or {}
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
            "novelty_available": bool(novelty_signal.get("novelty_available", False)),
            "novelty_source": novelty_signal.get("novelty_source", "unavailable"),
            "novelty_score": 0.0,
            "novelty_status": "no_data",
            "novelty_reason": "empty_window",
            "novelty_signals": [],
            "model_available": bool(model_signal.get("model_available", False)),
            "anomaly_score": 0.0,
            "anomaly_percentile": 0.0,
            "is_anomaly": False,
            "model_is_anomaly": bool(model_signal.get("is_anomaly", False)),
            "model_anomaly_score": float(model_signal.get("anomaly_score", 0.0) or 0.0),
            "model_anomaly_percentile": float(model_signal.get("anomaly_percentile", 0.0) or 0.0),
            "model_source": model_signal.get("source", "unavailable"),
            "records_evaluated": len(normalized_records),
            "window_key": metrics.get("window_key"),
        }
        summary["explanation"] = _build_explanation(summary, alerts)
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
        anomaly_fields = _derive_window_anomaly_fields(
            model_signal=model_signal,
            historical_signal=historical_signal,
            threat_score=score,
            detection_count=len(alerts),
            attack_predicted=False,
            risk_level="data_quality",
            anomaly_reason=pattern_reason,
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
            "novelty_available": bool(novelty_signal.get("novelty_available", False)),
            "novelty_source": novelty_signal.get("novelty_source", "unavailable"),
            "novelty_score": float(novelty_signal.get("novelty_score", 0.0) or 0.0),
            "novelty_status": novelty_signal.get("novelty_status", "unknown"),
            "novelty_reason": novelty_signal.get("novelty_reason", "unknown"),
            "novelty_signals": novelty_signal.get("novelty_signals", []),
            "model_available": bool(model_signal.get("model_available", False)),
            "model_source": model_signal.get("source", "unavailable"),
            "records_evaluated": len(normalized_records),
            "window_key": metrics.get("window_key"),
            **anomaly_fields,
        }
        summary["explanation"] = _build_explanation(summary, alerts)
        return alerts, summary

    if pattern_reason in {"llm_activity_drop", "llm_quality_degradation", "system_activity_drop"}:
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

    for signal in novelty_signal.get("novelty_signals", []):
        alerts.append(
            _alert(
                "novel_observed_values",
                str(signal.get("severity", "low")),
                int(signal.get("points", 0) or 0),
                {
                    "reason": novelty_signal.get("novelty_reason", "first_observed_values"),
                    "field": signal.get("field"),
                    "values": signal.get("values", []),
                    "value_count": signal.get("value_count", 0),
                },
            )
        )

    alerts.extend(_security_combination_alerts(metrics, count_threshold, pattern_reason))
    has_security_combination = _has_security_combination_alert(alerts)
    has_novelty_signal = bool(novelty_signal.get("novelty_signals", []))

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
    elif has_novelty_signal and pattern_reason in {"unknown", "insufficient_history", "general_pattern_break"}:
        summary_reason = "first_observed_values"
    if pattern_reason in {"llm_activity_drop", "llm_quality_degradation", "system_activity_drop"}:
        summary_risk_level = "service_activity_anomaly"
    if has_security_combination and pattern_status in {"unknown", "normal"}:
        summary_risk_level = "security_correlation"
    elif has_novelty_signal and pattern_status in {"unknown", "normal"}:
        summary_risk_level = "novel_activity"

    anomaly_fields = _derive_window_anomaly_fields(
        model_signal=model_signal,
        historical_signal=historical_signal,
        threat_score=threat_score,
        detection_count=len(alerts),
        attack_predicted=attack_predicted,
        risk_level=summary_risk_level,
        anomaly_reason=summary_reason,
    )

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
        "novelty_available": bool(novelty_signal.get("novelty_available", False)),
        "novelty_source": novelty_signal.get("novelty_source", "unavailable"),
        "novelty_score": float(novelty_signal.get("novelty_score", 0.0) or 0.0),
        "novelty_status": novelty_signal.get("novelty_status", "unknown"),
        "novelty_reason": novelty_signal.get("novelty_reason", "unknown"),
        "novelty_signals": novelty_signal.get("novelty_signals", []),
        "model_available": model_available,
        "model_source": model_signal.get("source", "unavailable"),
        "records_evaluated": len(normalized_records),
        "window_key": metrics.get("window_key"),
        **anomaly_fields,
    }
    summary["explanation"] = _build_explanation(summary, alerts)
    return alerts, summary


def apply_baseline_shift_context(
    raw_alerts: List[Dict[str, Any]],
    risk_summary: Dict[str, Any],
    recent_window_metrics: List[Dict[str, Any]],
    min_consecutive_windows: int = 6,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if str(risk_summary.get("anomaly_reason", "")) != "llm_activity_drop":
        return raw_alerts, risk_summary

    current_window_key = str(risk_summary.get("window_key") or "")
    consecutive_previous = 0
    for window in recent_window_metrics:
        if str(window.get("window_key") or "") == current_window_key:
            continue
        if int(float(window.get("total_records", 0) or 0)) <= 0:
            continue
        if str(window.get("anomaly_reason", "")) in BASELINE_SHIFT_REASONS:
            consecutive_previous += 1
            continue
        break

    if consecutive_previous + 1 < int(min_consecutive_windows):
        return raw_alerts, risk_summary

    updated_alerts = [
        _alert(
            "baseline_shift_candidate",
            "medium",
            10,
            {
                "reason": "repeated_llm_activity_drop",
                "consecutive_windows": consecutive_previous + 1,
                "previous_anomaly_reason": risk_summary.get("anomaly_reason"),
                "top_signals": risk_summary.get("pattern_signals", [])[:3],
            },
        )
    ]
    updated_summary = dict(risk_summary)
    updated_summary.update(
        {
            "threat_score": 10,
            "attack_predicted": False,
            "detection_count": len(updated_alerts),
            "risk_level": "baseline_shift",
            "anomaly_reason": "baseline_shift_candidate",
            "baseline_shift_windows": consecutive_previous + 1,
            "is_anomaly": True,
            "anomaly_score": 10.0,
            "anomaly_percentile": 10.0,
        }
    )
    updated_summary["explanation"] = _build_explanation(updated_summary, updated_alerts)
    return updated_alerts, updated_summary


def _build_explanation(summary: Dict[str, Any], alerts: List[Dict[str, Any]]) -> str:
    anomaly_reason = str(summary.get("anomaly_reason", "unknown"))
    threat_score = int(float(summary.get("threat_score", 0) or 0))

    if anomaly_reason == "empty_window":
        return "Empty window received; no alerts generated."

    if anomaly_reason == "possible_incomplete_window":
        return f"Incomplete window detected with threat score {threat_score} and {len(alerts)} alert(s)."

    if anomaly_reason == "llm_activity_drop":
        return f"LLM activity drop detected with threat score {threat_score} and {len(alerts)} alert(s)."

    if anomaly_reason == "llm_quality_degradation":
        return f"LLM quality degradation detected with threat score {threat_score} and {len(alerts)} alert(s)."

    if anomaly_reason == "system_activity_drop":
        return f"System activity drop detected with threat score {threat_score} and {len(alerts)} alert(s)."

    if anomaly_reason == "baseline_shift_candidate":
        windows = int(float(summary.get("baseline_shift_windows", 0) or 0))
        return f"Repeated LLM activity drops suggest a baseline shift after {windows} window(s)."

    if anomaly_reason == "first_observed_values":
        return f"New observed values detected with threat score {threat_score} and {len(alerts)} alert(s)."

    return f"{anomaly_reason.replace('_', ' ').strip().capitalize()} detected with threat score {threat_score} and {len(alerts)} alert(s)."


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


def _derive_window_anomaly_fields(
    model_signal: Dict[str, Any],
    historical_signal: Dict[str, Any],
    threat_score: int,
    detection_count: int,
    attack_predicted: bool,
    risk_level: str,
    anomaly_reason: str,
) -> Dict[str, Any]:
    model_is_anomaly = bool(model_signal.get("is_anomaly", False))
    model_score = _as_float(model_signal.get("anomaly_score"))
    model_percentile = _as_float(model_signal.get("anomaly_percentile"))
    pattern_score = _as_float(historical_signal.get("pattern_score"))
    pattern_status = str(historical_signal.get("pattern_status", "unknown"))

    historical_is_anomaly = (
        bool(historical_signal.get("historical_available", False))
        and pattern_status in ANOMALOUS_PATTERN_STATUSES
        and anomaly_reason not in {"empty_window", "insufficient_history"}
    )
    rule_is_anomaly = bool(attack_predicted or detection_count > 0 or int(threat_score) > 0)
    is_anomaly = bool(model_is_anomaly or historical_is_anomaly or rule_is_anomaly)

    if risk_level in {"no_data", "unknown"} and anomaly_reason in {"empty_window", "insufficient_history"}:
        is_anomaly = bool(model_is_anomaly and risk_level != "no_data")

    model_signal_score = model_percentile if model_percentile > 0.0 else min(100.0, model_score)
    anomaly_score = max(
        0.0,
        min(100.0, model_signal_score),
        min(100.0, pattern_score),
        min(100.0, float(threat_score)),
    )
    anomaly_percentile = max(
        0.0,
        min(100.0, model_percentile),
        min(100.0, pattern_score),
        min(100.0, float(threat_score)),
    )

    if is_anomaly and anomaly_score <= 0.0:
        anomaly_score = max(1.0, min(100.0, float(threat_score) or pattern_score or model_signal_score))
    if is_anomaly and anomaly_percentile <= 0.0:
        anomaly_percentile = anomaly_score

    return {
        "is_anomaly": is_anomaly,
        "anomaly_score": anomaly_score,
        "anomaly_percentile": anomaly_percentile,
        "model_is_anomaly": model_is_anomaly,
        "model_anomaly_score": model_score,
        "model_anomaly_percentile": model_percentile,
    }


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
