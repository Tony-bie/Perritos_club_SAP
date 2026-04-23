from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

LLM_TYPES = {"LLM_REQUEST", "LLM_ERROR", "LLM_TIMEOUT"}


def normalize_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    ingested_at = datetime.now(timezone.utc).isoformat()

    for record in records:
        item = dict(record)
        log_type = str(item.get("sap_function_log_type", ""))
        item["is_llm_log"] = log_type in LLM_TYPES
        item["is_system_log"] = not item["is_llm_log"]
        item["ingested_at"] = ingested_at
        normalized.append(item)

    return normalized
