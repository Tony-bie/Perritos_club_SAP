from __future__ import annotations

from typing import Any, Dict, List


NOVELTY_FIELDS = {
    "observed_log_types": "medium",
    "observed_service_ids": "low",
    "observed_http_status_codes": "low",
    "observed_llm_model_ids": "low",
}

HIGH_SIGNAL_LOG_TYPES = {"SECURITY", "ERROR", "LLM_ERROR", "LLM_TIMEOUT"}
HIGH_SIGNAL_HTTP_STATUS_CODES = {"401", "403", "429", "500", "502", "503", "504"}


def score_novelty_pattern(
    current_metrics: Dict[str, Any],
    history_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    signals: List[Dict[str, Any]] = []

    for field_name, default_severity in NOVELTY_FIELDS.items():
        current_values = _value_set(current_metrics.get(field_name))
        if not current_values:
            continue

        known_values = set()
        for row in history_rows:
            known_values.update(_value_set(row.get(field_name)))

        new_values = sorted(current_values - known_values)
        if not new_values:
            continue

        severity = _severity_for_new_values(field_name, new_values, default_severity)
        points = _points_for_severity(severity)
        signals.append(
            {
                "field": field_name,
                "values": new_values[:10],
                "value_count": len(new_values),
                "severity": severity,
                "points": points,
            }
        )

    novelty_score = min(100.0, sum(float(signal["points"]) for signal in signals))
    return {
        "novelty_available": True,
        "novelty_source": f"window_metrics:{len(history_rows)}",
        "novelty_score": novelty_score,
        "novelty_status": "novel_activity" if signals else "known_activity",
        "novelty_reason": "first_observed_values" if signals else "no_novel_values",
        "novelty_signals": signals,
    }


def _value_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    cleaned = str(value).strip()
    return {cleaned} if cleaned else set()


def _severity_for_new_values(field_name: str, values: List[str], default_severity: str) -> str:
    normalized_values = {value.upper() for value in values}
    if field_name == "observed_log_types" and normalized_values & HIGH_SIGNAL_LOG_TYPES:
        return "medium"
    if field_name == "observed_http_status_codes" and normalized_values & HIGH_SIGNAL_HTTP_STATUS_CODES:
        return "medium"
    return default_severity


def _points_for_severity(severity: str) -> int:
    if severity == "high":
        return 18
    if severity == "medium":
        return 10
    return 5
