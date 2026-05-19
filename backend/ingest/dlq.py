"""DLQ helper utilities for ingestion module."""
import os
import json
import time
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# default mock DLQ file (used by mock runner and inspector/autoposter)
from ..core.config import MOCK_DLQ_FILE as DLQ_FILE


def append_to_mock_dlq(item: Dict[str, Any]) -> None:
    """Append a DLQ item (dict) to the mock DLQ JSONL file."""
    try:
        os.makedirs(os.path.dirname(DLQ_FILE), exist_ok=True)
        with open(DLQ_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, default=str) + "\n")
        logger.debug("Appended item to mock DLQ: %s", item.get("failed", {}).get("event_id"))
    except Exception:
        logger.exception("Failed to append to mock DLQ")


def read_mock_dlq(limit: int = 100) -> List[Dict[str, Any]]:
    """Read up to `limit` items from the mock DLQ file (most recent first)."""
    if not os.path.exists(DLQ_FILE):
        return []
    out: List[Dict[str, Any]] = []
    try:
        with open(DLQ_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        for l in lines:
            try:
                out.append(json.loads(l))
            except Exception:
                logger.warning("Skipping invalid DLQ line")
    except Exception:
        logger.exception("Failed to read mock DLQ file")
    return out
