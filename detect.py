from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List


def detect_error_security_spike(
    normalized_records: List[Dict[str, Any]],
    combined_threshold: int = 25,
) -> List[Dict[str, Any]]:
    per_ip = defaultdict(lambda: {"error_count": 0, "security_count": 0, "total": 0})

    for record in normalized_records:
        if not record.get("is_system_log", False):
            continue

        ip = record.get("client_ip") or "unknown"
        log_type = str(record.get("sap_function_log_type", ""))
        if log_type not in {"ERROR", "SECURITY"}:
            continue

        per_ip[ip]["total"] += 1
        if log_type == "ERROR":
            per_ip[ip]["error_count"] += 1
        if log_type == "SECURITY":
            per_ip[ip]["security_count"] += 1

    alerts: List[Dict[str, Any]] = []
    for ip, counts in per_ip.items():
        if counts["total"] >= combined_threshold:
            alerts.append(
                {
                    "alert_type": "SYSTEM_IP_ERROR_SECURITY_SPIKE",
                    "severity": "high",
                    "client_ip": ip,
                    "threshold": combined_threshold,
                    "counts": counts,
                }
            )

    return alerts
