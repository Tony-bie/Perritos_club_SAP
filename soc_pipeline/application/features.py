from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from soc_pipeline.domain.constants import LLM_LOG_TYPES
from soc_pipeline.domain.models import UtcWindow
from soc_pipeline.shared.runtime import ratio, require_pandas


def current_utc_window(reference: datetime | None = None) -> UtcWindow:
    now = reference or datetime.now(timezone.utc)
    minute = 0 if now.minute < 30 else 30
    start = now.replace(minute=minute, second=0, microsecond=0)
    end = start + timedelta(minutes=30)
    return UtcWindow(start=start, end=end)


def normalize_records(records: list[dict[str, Any]]) -> Any:
    pd = require_pandas()
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=["sap_function_log_type"])

    if "sap_function_log_type" not in df.columns:
        df["sap_function_log_type"] = pd.NA

    if "_id" in df.columns:
        df["_id"] = df["_id"].astype("string")
        df = df.drop_duplicates(subset="_id", keep="last")

    df["is_llm_log"] = df["sap_function_log_type"].isin(LLM_LOG_TYPES)
    df["is_system_log"] = ~df["is_llm_log"]

    for numeric_column in ["http_status_code", "llm_cost_usd", "llm_response_time_ms"]:
        if numeric_column in df.columns:
            df[numeric_column] = pd.to_numeric(df[numeric_column], errors="coerce")

    if "@timestamp" in df.columns:
        df["@timestamp"] = df["@timestamp"].astype("string")

    return df


def build_ip_features(df: Any, window: UtcWindow) -> Any:
    pd = require_pandas()
    empty_columns = [
        "window_key",
        "client_ip",
        "event_count",
        "distinct_services",
        "error_count",
        "security_count",
        "warning_count",
        "audit_count",
        "http_4xx_count",
        "http_5xx_count",
    ]
    if "client_ip" not in df.columns:
        return pd.DataFrame(columns=empty_columns)

    system_df = df[df["is_system_log"]].copy()
    system_df = system_df[system_df["client_ip"].notna()].copy()
    if system_df.empty:
        return pd.DataFrame(columns=empty_columns)

    if "service_id" not in system_df.columns:
        system_df["service_id"] = pd.NA
    if "http_status_code" not in system_df.columns:
        system_df["http_status_code"] = pd.NA

    ip_features = (
        system_df.groupby("client_ip", dropna=True)
        .agg(
            event_count=("sap_function_log_type", "count"),
            distinct_services=("service_id", "nunique"),
            error_count=("sap_function_log_type", lambda s: int((s == "ERROR").sum())),
            security_count=("sap_function_log_type", lambda s: int((s == "SECURITY").sum())),
            warning_count=("sap_function_log_type", lambda s: int((s == "WARNING").sum())),
            audit_count=("sap_function_log_type", lambda s: int((s == "AUDIT").sum())),
            http_4xx_count=("http_status_code", lambda s: int(((s >= 400) & (s < 500)).sum())),
            http_5xx_count=("http_status_code", lambda s: int(((s >= 500) & (s < 600)).sum())),
        )
        .reset_index()
    )
    ip_features.insert(0, "window_key", window.key)
    return ip_features


def build_llm_features(df: Any, window: UtcWindow) -> Any:
    pd = require_pandas()
    empty_columns = [
        "window_key",
        "llm_model_id",
        "event_count",
        "request_count",
        "timeout_count",
        "error_count",
        "avg_latency_ms",
        "p95_latency_ms",
        "total_cost_usd",
    ]
    if "llm_model_id" not in df.columns:
        return pd.DataFrame(columns=empty_columns)

    llm_df = df[df["is_llm_log"]].copy()
    llm_df = llm_df[llm_df["llm_model_id"].notna()].copy()
    if llm_df.empty:
        return pd.DataFrame(columns=empty_columns)

    if "llm_response_time_ms" not in llm_df.columns:
        llm_df["llm_response_time_ms"] = pd.NA
    if "llm_cost_usd" not in llm_df.columns:
        llm_df["llm_cost_usd"] = pd.NA

    llm_features = (
        llm_df.groupby("llm_model_id", dropna=True)
        .agg(
            event_count=("sap_function_log_type", "count"),
            request_count=("sap_function_log_type", lambda s: int((s == "LLM_REQUEST").sum())),
            timeout_count=("sap_function_log_type", lambda s: int((s == "LLM_TIMEOUT").sum())),
            error_count=("sap_function_log_type", lambda s: int((s == "LLM_ERROR").sum())),
            avg_latency_ms=("llm_response_time_ms", "mean"),
            p95_latency_ms=("llm_response_time_ms", lambda s: float(s.quantile(0.95)) if s.notna().any() else 0.0),
            total_cost_usd=("llm_cost_usd", "sum"),
        )
        .reset_index()
    )
    llm_features.insert(0, "window_key", window.key)
    llm_features["avg_latency_ms"] = llm_features["avg_latency_ms"].fillna(0.0)
    llm_features["p95_latency_ms"] = llm_features["p95_latency_ms"].fillna(0.0)
    llm_features["total_cost_usd"] = llm_features["total_cost_usd"].fillna(0.0)
    return llm_features


def build_window_metrics(
    df: Any,
    window: UtcWindow,
    ip_features: Any,
    history_df: Any,
) -> dict[str, Any]:
    pd = require_pandas()
    system_df = df[df["is_system_log"]].copy()
    llm_df = df[df["is_llm_log"]].copy()

    log_counts = df["sap_function_log_type"].value_counts(dropna=False).to_dict()
    total_records = int(len(df))
    system_log_count = int(len(system_df))
    llm_log_count = int(len(llm_df))
    error_count = int(log_counts.get("ERROR", 0))
    security_count = int(log_counts.get("SECURITY", 0))
    warning_count = int(log_counts.get("WARNING", 0))
    audit_count = int(log_counts.get("AUDIT", 0))
    debug_count = int(log_counts.get("DEBUG", 0))
    perf_count = int(log_counts.get("PERF", 0))
    llm_request_count = int(log_counts.get("LLM_REQUEST", 0))
    llm_timeout_count = int(log_counts.get("LLM_TIMEOUT", 0))
    llm_error_count = int(log_counts.get("LLM_ERROR", 0))

    http_4xx_count = 0
    http_5xx_count = 0
    unique_client_ips = 0
    unique_services = 0

    if "http_status_code" in system_df.columns:
        http_4xx_count = int(((system_df["http_status_code"] >= 400) & (system_df["http_status_code"] < 500)).sum())
        http_5xx_count = int(((system_df["http_status_code"] >= 500) & (system_df["http_status_code"] < 600)).sum())
    if "client_ip" in system_df.columns:
        unique_client_ips = int(system_df["client_ip"].dropna().nunique())
    if "service_id" in system_df.columns:
        unique_services = int(system_df["service_id"].dropna().nunique())

    top_service_event_share = 0.0
    unique_ip_service_pairs = 0
    if "service_id" in system_df.columns and system_log_count > 0:
        service_counts = system_df["service_id"].dropna().value_counts()
        if not service_counts.empty:
            top_service_event_share = ratio(int(service_counts.max()), system_log_count)
        if "client_ip" in system_df.columns:
            pairs = system_df[["client_ip", "service_id"]].dropna()
            unique_ip_service_pairs = int(len(pairs.drop_duplicates()))

    avg_llm_latency_ms = 0.0
    p95_llm_latency_ms = 0.0
    total_llm_cost_usd = 0.0
    llm_model_entropy = 0.0
    if "llm_response_time_ms" in llm_df.columns and llm_df["llm_response_time_ms"].notna().any():
        avg_llm_latency_ms = float(llm_df["llm_response_time_ms"].mean())
        p95_llm_latency_ms = float(llm_df["llm_response_time_ms"].quantile(0.95))
    if "llm_cost_usd" in llm_df.columns and llm_df["llm_cost_usd"].notna().any():
        total_llm_cost_usd = float(llm_df["llm_cost_usd"].sum())
    if "llm_model_id" in llm_df.columns:
        llm_model_entropy = normalized_entropy(llm_df["llm_model_id"].dropna().value_counts())

    max_events_from_single_ip = int(ip_features["event_count"].max()) if not ip_features.empty else 0
    max_services_from_single_ip = int(ip_features["distinct_services"].max()) if not ip_features.empty else 0
    suspicious_ip_count = int((ip_features["event_count"] >= 15).sum()) if not ip_features.empty else 0
    avg_events_per_ip = ratio(system_log_count, unique_client_ips)
    avg_events_per_service = ratio(system_log_count, unique_services)
    top_ip_event_share = ratio(max_events_from_single_ip, system_log_count)
    suspicious_ip_ratio = ratio(suspicious_ip_count, unique_client_ips)
    ip_burst_ratio = ratio(max_events_from_single_ip, avg_events_per_ip) if avg_events_per_ip > 0 else 0.0
    pair_reuse_ratio = ratio(system_log_count, unique_ip_service_pairs)
    client_ip_entropy = normalized_entropy(system_df["client_ip"].dropna().value_counts()) if "client_ip" in system_df.columns else 0.0
    service_entropy = normalized_entropy(system_df["service_id"].dropna().value_counts()) if "service_id" in system_df.columns else 0.0

    recent_history = history_df.tail(12).copy()
    baselines = {}
    baseline_columns = [
        "total_records",
        "error_count",
        "security_count",
        "system_error_rate",
        "security_error_ratio",
        "http_5xx_count",
        "max_events_from_single_ip",
        "top_ip_event_share",
        "unique_client_ips",
        "unique_services",
        "llm_timeout_rate",
        "llm_timeout_plus_error_rate",
        "avg_llm_latency_ms",
        "p95_llm_latency_ms",
        "total_llm_cost_usd",
    ]
    for column in baseline_columns:
        if column in recent_history.columns and recent_history[column].notna().any():
            baselines[f"baseline_{column}"] = float(recent_history[column].mean())
        else:
            baselines[f"baseline_{column}"] = 0.0

    system_error_rate = ratio(error_count, system_log_count)
    http_4xx_rate = ratio(http_4xx_count, system_log_count)
    http_5xx_rate = ratio(http_5xx_count, system_log_count)
    llm_timeout_rate = ratio(llm_timeout_count, llm_log_count)
    llm_error_rate = ratio(llm_error_count, llm_log_count)
    llm_timeout_plus_error_rate = ratio(llm_timeout_count + llm_error_count, llm_log_count)
    llm_cost_per_request = ratio(total_llm_cost_usd, llm_request_count)
    security_error_ratio = ratio(security_count + error_count, total_records)

    deltas = {
        "delta_total_records": total_records - baselines["baseline_total_records"],
        "delta_error_count": error_count - baselines["baseline_error_count"],
        "delta_security_count": security_count - baselines["baseline_security_count"],
        "delta_unique_client_ips": unique_client_ips - baselines["baseline_unique_client_ips"],
        "delta_unique_services": unique_services - baselines["baseline_unique_services"],
        "delta_avg_llm_latency_ms": avg_llm_latency_ms - baselines["baseline_avg_llm_latency_ms"],
        "delta_p95_llm_latency_ms": p95_llm_latency_ms - baselines["baseline_p95_llm_latency_ms"],
        "delta_total_llm_cost_usd": total_llm_cost_usd - baselines["baseline_total_llm_cost_usd"],
        "delta_top_ip_event_share": top_ip_event_share - baselines["baseline_top_ip_event_share"],
        "delta_llm_timeout_plus_error_rate": llm_timeout_plus_error_rate - baselines["baseline_llm_timeout_plus_error_rate"],
    }

    return {
        "window_key": window.key,
        "window_start_utc": window.start.isoformat(),
        "window_end_utc": window.end.isoformat(),
        "total_records": total_records,
        "system_log_count": system_log_count,
        "llm_log_count": llm_log_count,
        "error_count": error_count,
        "security_count": security_count,
        "warning_count": warning_count,
        "audit_count": audit_count,
        "debug_count": debug_count,
        "perf_count": perf_count,
        "http_4xx_count": http_4xx_count,
        "http_5xx_count": http_5xx_count,
        "unique_client_ips": unique_client_ips,
        "unique_services": unique_services,
        "unique_ip_service_pairs": unique_ip_service_pairs,
        "max_events_from_single_ip": max_events_from_single_ip,
        "max_services_from_single_ip": max_services_from_single_ip,
        "suspicious_ip_count": suspicious_ip_count,
        "avg_events_per_ip": round(avg_events_per_ip, 6),
        "avg_events_per_service": round(avg_events_per_service, 6),
        "top_ip_event_share": round(top_ip_event_share, 6),
        "top_service_event_share": round(top_service_event_share, 6),
        "suspicious_ip_ratio": round(suspicious_ip_ratio, 6),
        "ip_burst_ratio": round(ip_burst_ratio, 6),
        "pair_reuse_ratio": round(pair_reuse_ratio, 6),
        "client_ip_entropy": round(client_ip_entropy, 6),
        "service_entropy": round(service_entropy, 6),
        "llm_request_count": llm_request_count,
        "llm_timeout_count": llm_timeout_count,
        "llm_error_count": llm_error_count,
        "llm_cost_per_request": round(llm_cost_per_request, 6),
        "llm_model_entropy": round(llm_model_entropy, 6),
        "avg_llm_latency_ms": round(avg_llm_latency_ms, 3),
        "p95_llm_latency_ms": round(p95_llm_latency_ms, 3),
        "total_llm_cost_usd": round(total_llm_cost_usd, 6),
        "system_error_rate": round(system_error_rate, 6),
        "http_4xx_rate": round(http_4xx_rate, 6),
        "http_5xx_rate": round(http_5xx_rate, 6),
        "llm_timeout_rate": round(llm_timeout_rate, 6),
        "llm_error_rate": round(llm_error_rate, 6),
        "llm_timeout_plus_error_rate": round(llm_timeout_plus_error_rate, 6),
        "security_error_ratio": round(security_error_ratio, 6),
        "log_type_counts": log_counts,
        **baselines,
        **deltas,
    }


def normalized_entropy(value_counts: Any) -> float:
    if value_counts is None or len(value_counts) <= 1:
        return 0.0

    total = float(value_counts.sum())
    if total <= 0:
        return 0.0

    probabilities = [float(count) / total for count in value_counts.tolist() if float(count) > 0.0]
    if len(probabilities) <= 1:
        return 0.0

    entropy = -sum(probability * math.log(probability, 2) for probability in probabilities)
    max_entropy = math.log(len(probabilities), 2)
    if max_entropy <= 0:
        return 0.0
    return entropy / max_entropy
