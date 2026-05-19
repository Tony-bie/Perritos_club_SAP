"""Simple escalation playbook for alerts.

This module contains logic to decide whether an alert/window should be
escalated and which actions to take. It is intentionally simple and
observable so it can be extended later with rules, thresholds, and
integration hooks.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def decide_escalation_for_alert(alert: Dict[str, Any], window_metrics: Dict[str, Any], settings) -> Dict[str, Any]:
    """Decide escalation level for a single alert.

    Returns a dict with keys:
      - level: one of "NONE", "PENDING", "ESCALATED", "SOC"
      - reason: human-readable reason
      - actions: list of actions to perform (e.g. "notify_soc")
    """
    level = "NONE"
    actions: List[str] = []
    reason = "no escalation conditions met"

    severity = (alert.get("severity") or "").lower()
    payload = alert.get("payload") or {}

    # High severity immediately escalates to SOC
    if severity == "high":
        level = "SOC"
        actions.append("notify_soc")
        reason = "high severity"
        return {"level": level, "reason": reason, "actions": actions}

    # If payload contains a numeric count, compare to error threshold
    try:
        count = int(payload.get("count", 0) or 0)
    except Exception:
        count = 0

    if count >= getattr(settings, "error_security_threshold", 100):
        level = "ESCALATED"
        actions.append("notify_ops")
        reason = f"count >= {settings.error_security_threshold}"
        return {"level": level, "reason": reason, "actions": actions}

    # If the window-level threat score is high, escalate to pending/ops
    try:
        threat_score = int(window_metrics.get("threat_score", 0) or 0)
    except Exception:
        threat_score = 0

    if threat_score >= getattr(settings, "attack_score_threshold", 70):
        level = "PENDING"
        actions.append("review")
        reason = f"window threat_score >= {settings.attack_score_threshold}"
        return {"level": level, "reason": reason, "actions": actions}

    return {"level": level, "reason": reason, "actions": actions}


def execute_playbook_for_alert(alert: Dict[str, Any], window_metrics: Dict[str, Any], settings, client=None, store=None) -> Dict[str, Any]:
    """Execute playbook actions for a single alert.

    - Decides escalation level.
    - If `notify_soc` and `client` provided, submits an alert via `client.submit_alert`.
    - If `store` provided, logs an escalation event by inserting an alert of type
      `escalation` through `store.insert_alerts`.

    Returns the decision and any remote response from `client.submit_alert` under
    the `notification_response` key.
    """
    decision = decide_escalation_for_alert(alert, window_metrics, settings)
    resp = None
    try:
        if "notify_soc" in decision.get("actions", []) and client is not None:
            msg = f"Escalation: alert_id={alert.get('alert_id')} level={decision['level']} reason={decision['reason']}"
            try:
                resp = client.submit_alert(msg)
            except Exception as exc:
                logger.warning("Failed to notify SOC: %s", exc)

        # Record escalation in the store as an alert event for auditing
        if store is not None and decision.get("level") in {"PENDING", "ESCALATED", "SOC"}:
            esc_alert = {
                "alert_id": f"escalation-{alert.get('alert_id')}",
                "run_id": alert.get("run_id"),
                "detected_at_utc": alert.get("detected_at_utc"),
                "alert_type": "escalation",
                "severity": decision.get("level").lower(),
                "payload": {"source_alert": alert, "reason": decision.get("reason")},
            }
            try:
                store.insert_alerts([esc_alert])
            except Exception:
                logger.exception("Failed to record escalation in store")
    except Exception:
        logger.exception("Playbook execution failed")

    out = {"decision": decision, "notification_response": resp}
    return out
