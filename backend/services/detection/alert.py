from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4


ALERT_MESSAGE_MAX_LENGTH = 300


def format_alert_events(raw_alerts: List[Dict[str, Any]], run_id: str) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    events: List[Dict[str, Any]] = []

    for alert in raw_alerts:
        events.append(
            {
                "alert_id": str(uuid4()),
                "run_id": run_id,
                "detected_at_utc": now,
                "alert_type": alert.get("alert_type", "UNKNOWN"),
                "severity": alert.get("severity", "medium"),
                "payload": dict(alert),
            }
        )

    return events


def build_alert_submission_message(
    window_metrics: Dict[str, Any],
    raw_alerts: List[Dict[str, Any]],
    notification_reason: str | None = None,
) -> str:
    window_key = str(window_metrics.get("window_key") or "current_window")
    risk_level = str(window_metrics.get("risk_level") or "unknown").replace("_", " ")
    threat_score = int(window_metrics.get("threat_score", 0) or 0)
    attack_predicted = bool(window_metrics.get("attack_predicted", False))

    what = (
        f"Potential attack pattern detected for {window_key}"
        if attack_predicted
        else f"Security anomaly detected for {window_key}"
    )
    what = f"{what} (risk={risk_level}, score={threat_score})"

    when = _coerce_when(window_metrics)
    why = _build_why(
        window_metrics=window_metrics,
        raw_alerts=raw_alerts,
        notification_reason=notification_reason,
    )

    message = f"WHAT: {what}. WHEN: {when}. WHY: {why}."
    return _truncate_message(message, ALERT_MESSAGE_MAX_LENGTH)


def _coerce_when(window_metrics: Dict[str, Any]) -> str:
    for field in ("window_end", "saved_at_utc", "window_start"):
        value = window_metrics.get(field)
        if value:
            return str(value)
    return datetime.now(timezone.utc).isoformat()


def _build_why(
    window_metrics: Dict[str, Any],
    raw_alerts: List[Dict[str, Any]],
    notification_reason: str | None = None,
) -> str:
    detection_count = int(window_metrics.get("detection_count", len(raw_alerts)) or 0)
    threat_score = int(window_metrics.get("threat_score", 0) or 0)
    parts = []
    if notification_reason:
        parts.append(f"trigger={notification_reason}")
    parts.extend(
        [
            f"detection_count={detection_count}",
            f"threat_score={threat_score}",
        ]
    )

    if raw_alerts:
        top_alert = raw_alerts[0]
        top_type = str(top_alert.get("alert_type", "UNKNOWN")).upper()
        top_score = int(top_alert.get("score", 0) or 0)
        parts.append(f"top_signal={top_type}(score={top_score})")

        payload = top_alert.get("payload") if isinstance(top_alert.get("payload"), dict) else {}
        feature = payload.get("feature")
        if feature:
            parts.append(f"feature={feature}")

        robust_z = payload.get("abs_robust_z")
        try:
            if robust_z is not None:
                parts.append(f"robust_z={float(robust_z):.2f}")
        except (TypeError, ValueError):
            pass

    if bool(window_metrics.get("is_anomaly", False)):
        percentile = float(window_metrics.get("anomaly_percentile", 0.0) or 0.0)
        parts.append(f"model_anomaly_percentile={percentile:.1f}")

    return "; ".join(parts)


def should_submit_alert_notification(
    window_metrics: Dict[str, Any],
    raw_alerts: List[Dict[str, Any]],
    attack_score_threshold: int,
) -> tuple[bool, str]:
    if not raw_alerts:
        return False, "no_detection_signals"

    anomaly_reason = str(window_metrics.get("anomaly_reason", ""))
    if anomaly_reason == "possible_incomplete_window":
        return False, "suppressed_possible_incomplete_window"

    threat_score = int(window_metrics.get("threat_score", 0) or 0)
    attack_predicted = bool(window_metrics.get("attack_predicted", False))
    anomaly_percentile = float(window_metrics.get("anomaly_percentile", 0.0) or 0.0)
    is_anomaly = bool(window_metrics.get("is_anomaly", False))
    detection_count = int(window_metrics.get("detection_count", len(raw_alerts)) or 0)

    if attack_predicted:
        return True, "attack_predicted"

    if threat_score >= int(attack_score_threshold):
        return True, f"threat_score_gte_threshold:{threat_score}>={int(attack_score_threshold)}"

    if is_anomaly and anomaly_percentile >= 95.0 and detection_count >= 2:
        return True, f"model_extreme_percentile:{anomaly_percentile:.1f}"

    return False, "below_notification_threshold"


def _truncate_message(message: str, max_length: int) -> str:
    compact = " ".join(message.split()).strip()
    if len(compact) <= max_length:
        return compact
    return f"{compact[: max_length - 3].rstrip()}..."
