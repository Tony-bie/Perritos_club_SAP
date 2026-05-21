"""
Groups log records into 30-minute windows and computes ~25 metrics per window.

Metrics include error/security counts, LLM latency, HTTP codes, unique IPs,
and rate calculations. NUMERIC_FEATURE_COLUMNS lists all features used by
the ML model and the historical baseline.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Dict, List


NUMERIC_FEATURE_COLUMNS = [
    "total_records",
    "system_log_count",
    "llm_log_count",
    "error_count",
    "security_count",
    "warning_count",
    "audit_count",
    "debug_count",
    "unique_client_ips",
    "unique_services",
    "perf_count",
    "http_4xx_count",
    "http_5xx_count",
    "max_events_from_single_ip",
    "llm_request_count",
    "llm_error_count",
    "llm_timeout_count",
    "avg_llm_latency_ms",
    "p95_llm_latency_ms",
    "total_llm_cost_usd",
    "system_error_rate",
    "security_event_rate",
    "llm_error_rate",
    "llm_timeout_rate",
    "top_ip_event_share",
]

TIMESTAMP_FIELDS = (
    "@timestamp",
    "timestamp",
    "event_time",
    "log_ts",
    "time",
)


def _safe_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = (len(ordered) - 1) * max(0.0, min(1.0, percentile))
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _parse_timestamp(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    raw_value = str(value).strip()
    if not raw_value:
        return None
    if raw_value.endswith("Z"):
        raw_value = f"{raw_value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_timestamp(record: Dict[str, Any]) -> datetime | None:
    for field_name in TIMESTAMP_FIELDS:
        parsed = _parse_timestamp(record.get(field_name))
        if parsed is not None:
            return parsed
    return None


def _floor_half_hour(value: datetime) -> datetime:
    minute_slot = 0 if value.minute < 30 else 30
    return value.astimezone(timezone.utc).replace(minute=minute_slot, second=0, microsecond=0)


def _format_window_key(window_start: datetime, window_end: datetime) -> str:
    start = window_start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end = window_end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{start}_{end}"


def _window_key(window_start: str | None, window_end: str | None) -> str:
    parsed_start = _parse_timestamp(window_start)
    parsed_end = _parse_timestamp(window_end)
    if parsed_start and parsed_end:
        return _format_window_key(parsed_start, parsed_end)
    if window_start and window_end:
        start = window_start.replace(":", "").replace("-", "")
        end = window_end.replace(":", "").replace("-", "")
        return f"{start}_{end}"

    now = datetime.now(timezone.utc)
    current = _floor_half_hour(now)
    end = current + timedelta(minutes=30)
    return _format_window_key(current, end)


def _window_bounds(window_start: str | None, window_end: str | None) -> tuple[str | None, str | None]:
    parsed_start = _parse_timestamp(window_start)
    parsed_end = _parse_timestamp(window_end)
    if parsed_start and parsed_end:
        return parsed_start.isoformat(), parsed_end.isoformat()
    return window_start, window_end


def _timestamp_window_bounds(timestamp: datetime) -> tuple[str, str]:
    start = _floor_half_hour(timestamp)
    end = start + timedelta(minutes=30)
    return start.isoformat(), end.isoformat()


def build_window_metrics(
    normalized_records: List[Dict[str, Any]],
    window_start: str | None,
    window_end: str | None,
) -> Dict[str, Any]:
    window_start, window_end = _window_bounds(window_start, window_end)
    total_records = len(normalized_records)
    log_types = Counter(str(record.get("sap_function_log_type", "")).upper() for record in normalized_records)
    system_records = [record for record in normalized_records if record.get("is_system_log", False)]
    llm_records = [record for record in normalized_records if record.get("is_llm_log", False)]

    client_ips = [str(record.get("client_ip")) for record in system_records if record.get("client_ip")]
    service_ids = [str(record.get("service_id")) for record in system_records if record.get("service_id")]
    ip_counts = Counter(client_ips)

    http_status_codes = [_safe_float(record.get("http_status_code")) for record in system_records]
    llm_latencies = [_safe_float(record.get("llm_response_time_ms")) for record in llm_records]
    llm_latencies = [value for value in llm_latencies if value is not None]
    llm_costs = [_safe_float(record.get("llm_cost_usd")) for record in llm_records]
    llm_costs = [value for value in llm_costs if value is not None]

    http_4xx_count = sum(1 for code in http_status_codes if code is not None and 400 <= code < 500)
    http_5xx_count = sum(1 for code in http_status_codes if code is not None and 500 <= code < 600)
    llm_error_count = log_types.get("LLM_ERROR", 0)
    llm_timeout_count = log_types.get("LLM_TIMEOUT", 0)
    llm_request_count = log_types.get("LLM_REQUEST", 0)
    system_log_count = len(system_records)
    llm_log_count = len(llm_records)

    max_events_from_single_ip = max(ip_counts.values()) if ip_counts else 0
    top_ip_event_share = (max_events_from_single_ip / system_log_count) if system_log_count else 0.0

    metrics = {
        "window_key": _window_key(window_start, window_end),
        "window_start": window_start,
        "window_end": window_end,
        "total_records": total_records,
        "system_log_count": system_log_count,
        "llm_log_count": llm_log_count,
        "error_count": log_types.get("ERROR", 0),
        "security_count": log_types.get("SECURITY", 0),
        "warning_count": log_types.get("WARNING", 0),
        "audit_count": log_types.get("AUDIT", 0),
        "debug_count": log_types.get("DEBUG", 0),
        "unique_client_ips": len(set(client_ips)),
        "unique_services": len(set(service_ids)),
        "perf_count": log_types.get("PERF", 0),
        "http_4xx_count": http_4xx_count,
        "http_5xx_count": http_5xx_count,
        "max_events_from_single_ip": max_events_from_single_ip,
        "llm_request_count": llm_request_count,
        "llm_error_count": llm_error_count,
        "llm_timeout_count": llm_timeout_count,
        "avg_llm_latency_ms": mean(llm_latencies) if llm_latencies else 0.0,
        "p95_llm_latency_ms": _percentile(llm_latencies, 0.95) if llm_latencies else 0.0,
        "total_llm_cost_usd": sum(llm_costs),
        "system_error_rate": (log_types.get("ERROR", 0) / system_log_count) if system_log_count else 0.0,
        "security_event_rate": (log_types.get("SECURITY", 0) / system_log_count) if system_log_count else 0.0,
        "llm_error_rate": (llm_error_count / llm_log_count) if llm_log_count else 0.0,
        "llm_timeout_rate": (llm_timeout_count / llm_log_count) if llm_log_count else 0.0,
        "top_ip_event_share": top_ip_event_share,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return metrics


def build_window_metric_batches(
    normalized_records: List[Dict[str, Any]],
    window_start: str | None,
    window_end: str | None,
) -> List[tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    buckets: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    unbucketed: List[Dict[str, Any]] = []

    for record in normalized_records:
        timestamp = _record_timestamp(record)
        if timestamp is None:
            unbucketed.append(record)
            continue
        start, end = _timestamp_window_bounds(timestamp)
        buckets.setdefault((start, end), []).append(record)

    if not buckets:
        return [(build_window_metrics(normalized_records, window_start, window_end), normalized_records)]

    batches = [
        (build_window_metrics(records, start, end), records)
        for (start, end), records in sorted(buckets.items())
    ]
    if unbucketed:
        batches.append((build_window_metrics(unbucketed, window_start, window_end), unbucketed))
    return batches
