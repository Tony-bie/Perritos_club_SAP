from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4


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
                "payload": alert,
            }
        )

    return events
