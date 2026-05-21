"""
Fetches all log pages from the SAP SOC API for the current window.

Returns an IngestRunResult with timing/counts and the raw records list.
On error, returns status="failed" with empty records so the pipeline continues.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.services.clients.sap_soc import SAPSOCClient


@dataclass
class IngestRunResult:
    run_id: str
    status: str
    started_at_utc: str
    ended_at_utc: str
    duration_seconds: float
    window_start: str | None
    window_end: str | None
    total_pages_expected: int
    total_pages_fetched: int
    total_records_info: int
    total_records_fetched: int
    error_message: str | None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_ingestion_cycle(client: SAPSOCClient, run_id: str) -> tuple[IngestRunResult, List[Dict[str, Any]]]:
    started_at = datetime.now(timezone.utc)
    started_at_utc = started_at.isoformat()

    try:
        payload = client.fetch_current_window_all_pages()
        info = payload.get("info", {})
        pages = payload.get("pages", [])
        records = payload.get("records", [])

        ended_at = datetime.now(timezone.utc)
        result = IngestRunResult(
            run_id=run_id,
            status="success",
            started_at_utc=started_at_utc,
            ended_at_utc=ended_at.isoformat(),
            duration_seconds=(ended_at - started_at).total_seconds(),
            window_start=info.get("window_start"),
            window_end=info.get("window_end"),
            total_pages_expected=int(info.get("total_pages", 0)),
            total_pages_fetched=len(pages),
            total_records_info=int(info.get("total_records", 0)),
            total_records_fetched=len(records),
            error_message=None,
        )
        return result, records
    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        result = IngestRunResult(
            run_id=run_id,
            status="failed",
            started_at_utc=started_at_utc,
            ended_at_utc=ended_at.isoformat(),
            duration_seconds=(ended_at - started_at).total_seconds(),
            window_start=None,
            window_end=None,
            total_pages_expected=0,
            total_pages_fetched=0,
            total_records_info=0,
            total_records_fetched=0,
            error_message=str(exc),
        )
        return result, []


def ingest_result_to_dict(result: IngestRunResult) -> Dict[str, Any]:
    return asdict(result)
