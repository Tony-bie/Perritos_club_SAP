from __future__ import annotations

from statistics import median
from typing import Any, Dict, List

from backend.services.ingestion.features import NUMERIC_FEATURE_COLUMNS


CORE_VOLUME_FEATURES = {
    "total_records",
    "system_log_count",
    "llm_log_count",
}

LLM_ACTIVITY_DOWN_FEATURES = {
    "llm_log_count",
    "llm_request_count",
    "llm_error_count",
    "llm_timeout_count",
    "avg_llm_latency_ms",
    "p95_llm_latency_ms",
    "total_llm_cost_usd",
}

SYSTEM_ACTIVITY_DOWN_FEATURES = {
    "total_records",
    "system_log_count",
    "error_count",
    "security_count",
    "warning_count",
    "audit_count",
    "debug_count",
    "perf_count",
    "http_4xx_count",
    "http_5xx_count",
}

SECURITY_ATTACK_UP_FEATURES = {
    "security_count",
    "security_event_rate",
    "http_5xx_count",
    "system_error_rate",
    "top_ip_event_share",
    "max_events_from_single_ip",
}

LLM_DEGRADATION_UP_FEATURES = {
    "llm_error_rate",
    "llm_timeout_rate",
}


def score_historical_pattern(
    current_metrics: Dict[str, Any],
    history_rows: List[Dict[str, Any]],
    min_history_rows: int = 30,
) -> Dict[str, Any]:
    if len(history_rows) < min_history_rows:
        return {
            "historical_available": False,
            "historical_source": f"insufficient_history:{len(history_rows)}",
            "pattern_score": 0.0,
            "max_feature_deviation": 0.0,
            "pattern_status": "unknown",
            "pattern_reason": "insufficient_history",
            "pattern_signals": [],
        }

    signals: List[Dict[str, Any]] = []

    for feature in NUMERIC_FEATURE_COLUMNS:
        current_value = _as_float(_pick_value(current_metrics, feature))
        if current_value is None:
            continue

        historical_values = [_as_float(_pick_value(row, feature)) for row in history_rows]
        historical_values = [value for value in historical_values if value is not None]
        if len(historical_values) < min_history_rows:
            continue

        center = float(median(historical_values))
        deviations = [abs(value - center) for value in historical_values]
        mad = float(median(deviations))

        if mad <= 0.0:
            robust_z = 6.0 if current_value != center else 0.0
        else:
            robust_z = 0.6745 * (current_value - center) / mad

        abs_robust_z = abs(robust_z)
        if abs_robust_z < 3.0:
            continue

        severity, points = _severity_points(abs_robust_z)
        signals.append(
            {
                "feature": feature,
                "value": current_value,
                "median": center,
                "mad": mad,
                "robust_z": robust_z,
                "abs_robust_z": abs_robust_z,
                "direction": "higher_than_usual" if robust_z > 0 else "lower_than_usual",
                "severity": severity,
                "points": points,
            }
        )

    signals.sort(key=lambda signal: float(signal.get("abs_robust_z", 0.0)), reverse=True)

    pattern_score = min(100.0, sum(float(signal.get("points", 0.0)) for signal in signals))
    max_feature_deviation = max(
        [float(signal.get("abs_robust_z", 0.0)) for signal in signals],
        default=0.0,
    )

    return {
        "historical_available": True,
        "historical_source": f"robust_z:{len(history_rows)}",
        "pattern_score": pattern_score,
        "max_feature_deviation": max_feature_deviation,
        "pattern_status": _pattern_status(pattern_score, max_feature_deviation),
        "pattern_reason": _pattern_reason(signals),
        "pattern_signals": signals,
    }


def _severity_points(abs_robust_z: float) -> tuple[str, int]:
    if abs_robust_z >= 8.0:
        return "critical", 25
    if abs_robust_z >= 4.0:
        return "high", 15
    return "medium", 8


def _pattern_status(pattern_score: float, max_feature_deviation: float) -> str:
    if max_feature_deviation >= 8.0 or pattern_score >= 35.0:
        return "critical_anomaly"
    if max_feature_deviation >= 4.0 or pattern_score >= 20.0:
        return "high_anomaly"
    if max_feature_deviation >= 3.0 or pattern_score >= 12.0:
        return "suspicious"
    return "normal"


def _pattern_reason(signals: List[Dict[str, Any]]) -> str:
    strong_down_features = {
        str(signal.get("feature"))
        for signal in signals
        if str(signal.get("direction")) == "lower_than_usual"
        and float(signal.get("abs_robust_z", 0.0)) >= 4.0
    }
    strong_up_features = {
        str(signal.get("feature"))
        for signal in signals
        if str(signal.get("direction")) == "higher_than_usual"
        and float(signal.get("abs_robust_z", 0.0)) >= 3.0
    }
    very_strong_up_features = {
        str(signal.get("feature"))
        for signal in signals
        if str(signal.get("direction")) == "higher_than_usual"
        and float(signal.get("abs_robust_z", 0.0)) >= 4.0
    }

    attack_up_features = strong_up_features & SECURITY_ATTACK_UP_FEATURES
    very_strong_attack_up_features = very_strong_up_features & SECURITY_ATTACK_UP_FEATURES
    if very_strong_attack_up_features or len(attack_up_features) >= 2:
        return "possible_attack_pattern"
    if CORE_VOLUME_FEATURES.issubset(strong_down_features):
        return "possible_incomplete_window"
    if strong_down_features & LLM_ACTIVITY_DOWN_FEATURES:
        return "llm_activity_drop"
    if strong_up_features & LLM_DEGRADATION_UP_FEATURES:
        return "llm_quality_degradation"
    if strong_down_features & SYSTEM_ACTIVITY_DOWN_FEATURES:
        return "system_activity_drop"
    if strong_up_features:
        return "upward_pattern_break"
    if strong_down_features:
        return "downward_pattern_break"
    return "general_pattern_break"


def _pick_value(row: Dict[str, Any], key: str) -> Any:
    return row.get(key) if key in row else row.get(key.upper())


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
