from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.storage.backends.store import BaseStore, ResilientStore, SqliteStore


class FailingPrimaryStore(BaseStore):
    def __init__(self) -> None:
        self.raw_logs: List[Dict[str, Any]] = []
        self.ingest_runs: List[Dict[str, Any]] = []
        self.alerts: List[Dict[str, Any]] = []
        self.window_metrics: List[Dict[str, Any]] = []
        self.fail_writes = True

    def ensure_schema(self) -> None:
        return None

    def upsert_raw_logs(self, records: List[Dict[str, Any]]) -> int:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        self.raw_logs.extend(records)
        return len(records)

    def bulk_upsert_raw_logs(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        return self.upsert_raw_logs(records)

    def insert_ingest_run(self, ingest_run: Dict[str, Any]) -> None:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        self.ingest_runs.append(ingest_run)

    def insert_alerts(self, alerts: List[Dict[str, Any]]) -> int:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        self.alerts.extend(alerts)
        return len(alerts)

    def get_last_run(self) -> Optional[Dict[str, Any]]:
        return self.ingest_runs[-1] if self.ingest_runs else None

    def upsert_window_metrics(self, metrics: Dict[str, Any]) -> None:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        self.window_metrics.append(metrics)

    def bulk_upsert_window_metrics(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        self.window_metrics.extend(records)
        return len(records)

    def get_recent_window_metrics(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.window_metrics[-limit:]

    def get_recent_alerts(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.alerts[-limit:]

    def get_recent_ingest_runs(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.ingest_runs[-limit:]

    def get_dashboard_summary(self, time_window_hours: int = 24) -> Dict[str, Any]:
        return {"total_alerts": len(self.alerts)}

    def get_recent_window_features(self, limit: int = 200) -> List[Dict[str, Any]]:
        return []

    def get_latest_window_metrics(self) -> Optional[Dict[str, Any]]:
        return self.window_metrics[-1] if self.window_metrics else None

    def call_cleanup_procedure(self, retention_days: int = 90) -> Dict[str, Any]:
        return {"status": "ok"}


class IdempotentPrimaryStore(FailingPrimaryStore):
    def __init__(self) -> None:
        super().__init__()
        self.raw_logs_by_id: Dict[str, Dict[str, Any]] = {}
        self.ingest_runs_by_id: Dict[str, Dict[str, Any]] = {}
        self.alerts_by_id: Dict[str, Dict[str, Any]] = {}
        self.window_metrics_by_key: Dict[str, Dict[str, Any]] = {}

    @property
    def raw_logs(self) -> List[Dict[str, Any]]:  # type: ignore[override]
        return list(self.raw_logs_by_id.values())

    @raw_logs.setter
    def raw_logs(self, value: List[Dict[str, Any]]) -> None:
        self.raw_logs_by_id = {}

    @property
    def ingest_runs(self) -> List[Dict[str, Any]]:  # type: ignore[override]
        return list(self.ingest_runs_by_id.values())

    @ingest_runs.setter
    def ingest_runs(self, value: List[Dict[str, Any]]) -> None:
        self.ingest_runs_by_id = {}

    @property
    def alerts(self) -> List[Dict[str, Any]]:  # type: ignore[override]
        return list(self.alerts_by_id.values())

    @alerts.setter
    def alerts(self, value: List[Dict[str, Any]]) -> None:
        self.alerts_by_id = {}

    @property
    def window_metrics(self) -> List[Dict[str, Any]]:  # type: ignore[override]
        return list(self.window_metrics_by_key.values())

    @window_metrics.setter
    def window_metrics(self, value: List[Dict[str, Any]]) -> None:
        self.window_metrics_by_key = {}

    def upsert_raw_logs(self, records: List[Dict[str, Any]]) -> int:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        for record in records:
            key = str(record.get("_id") or "")
            self.raw_logs_by_id[key] = record
        return len(records)

    def insert_ingest_run(self, ingest_run: Dict[str, Any]) -> None:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        self.ingest_runs_by_id[str(ingest_run.get("run_id"))] = ingest_run

    def insert_alerts(self, alerts: List[Dict[str, Any]]) -> int:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        for alert in alerts:
            self.alerts_by_id[str(alert.get("alert_id"))] = alert
        return len(alerts)

    def upsert_window_metrics(self, metrics: Dict[str, Any]) -> None:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        self.window_metrics_by_key[str(metrics.get("window_key"))] = metrics

    def bulk_upsert_window_metrics(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        if self.fail_writes:
            raise RuntimeError("primary unavailable")
        for metrics in records:
            self.window_metrics_by_key[str(metrics.get("window_key"))] = metrics
        return len(records)


class ResilientStoreTests(unittest.TestCase):
    def test_writes_fall_back_to_sqlite_when_primary_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fallback = SqliteStore(str(Path(tmp_dir) / "fallback.db"))
            primary = FailingPrimaryStore()
            store = ResilientStore(primary=primary, fallback=fallback)
            store.ensure_schema()

            records = [
                {
                    "_id": "log-1",
                    "@timestamp": "2026-05-10T10:00:00+00:00",
                    "is_llm_log": False,
                    "is_system_log": True,
                    "ingested_at": "2026-05-10T10:00:05+00:00",
                }
            ]
            ingest_run = {
                "run_id": "run-1",
                "status": "success",
                "started_at_utc": "2026-05-10T10:00:00+00:00",
                "ended_at_utc": "2026-05-10T10:00:10+00:00",
                "duration_seconds": 10.0,
                "window_start": "2026-05-10T10:00:00+00:00",
                "window_end": "2026-05-10T10:30:00+00:00",
                "total_pages_expected": 1,
                "total_pages_fetched": 1,
                "total_records_info": 1,
                "total_records_fetched": 1,
                "error_message": None,
            }
            metrics = {
                "window_key": "20260510T100000Z_20260510T103000Z",
                "run_id": "run-1",
                "window_start": "2026-05-10T10:00:00+00:00",
                "window_end": "2026-05-10T10:30:00+00:00",
                "total_records": 1,
                "threat_score": 0,
                "detection_count": 0,
                "attack_predicted": False,
                "model_available": False,
                "is_anomaly": False,
                "anomaly_score": 0.0,
                "anomaly_percentile": 0.0,
                "saved_at_utc": "2026-05-10T10:00:10+00:00",
            }
            alert = {
                "alert_id": "alert-1",
                "run_id": "run-1",
                "detected_at_utc": "2026-05-10T10:00:11+00:00",
                "alert_type": "TEST",
                "severity": "low",
                "payload": {"score": 1},
            }

            self.assertEqual(store.bulk_upsert_raw_logs(records), 1)
            store.insert_ingest_run(ingest_run)
            store.upsert_window_metrics(metrics)
            self.assertEqual(store.insert_alerts([alert]), 1)

            fallback_status = store.get_fallback_status()
            self.assertTrue(fallback_status["enabled"])
            self.assertFalse(fallback_status["primary_available"])
            self.assertEqual(fallback_status["pending_counts"]["raw_logs"], 1)
            self.assertEqual(fallback_status["pending_counts"]["ingest_runs"], 1)
            self.assertEqual(fallback_status["pending_counts"]["window_metrics"], 1)
            self.assertEqual(fallback_status["pending_counts"]["alerts_events"], 1)

    def test_manual_resync_moves_pending_records_to_primary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fallback = SqliteStore(str(Path(tmp_dir) / "fallback.db"))
            primary = FailingPrimaryStore()
            store = ResilientStore(primary=primary, fallback=fallback)
            store.ensure_schema()

            records = [
                {
                    "_id": "log-1",
                    "@timestamp": "2026-05-10T10:00:00+00:00",
                    "is_llm_log": False,
                    "is_system_log": True,
                    "ingested_at": "2026-05-10T10:00:05+00:00",
                }
            ]
            ingest_run = {
                "run_id": "run-1",
                "status": "success",
                "started_at_utc": "2026-05-10T10:00:00+00:00",
                "ended_at_utc": "2026-05-10T10:00:10+00:00",
                "duration_seconds": 10.0,
                "window_start": "2026-05-10T10:00:00+00:00",
                "window_end": "2026-05-10T10:30:00+00:00",
                "total_pages_expected": 1,
                "total_pages_fetched": 1,
                "total_records_info": 1,
                "total_records_fetched": 1,
                "error_message": None,
            }
            metrics = {
                "window_key": "20260510T100000Z_20260510T103000Z",
                "run_id": "run-1",
                "window_start": "2026-05-10T10:00:00+00:00",
                "window_end": "2026-05-10T10:30:00+00:00",
                "total_records": 1,
                "threat_score": 0,
                "detection_count": 0,
                "attack_predicted": False,
                "model_available": False,
                "is_anomaly": False,
                "anomaly_score": 0.0,
                "anomaly_percentile": 0.0,
                "saved_at_utc": "2026-05-10T10:00:10+00:00",
            }
            alert = {
                "alert_id": "alert-1",
                "run_id": "run-1",
                "detected_at_utc": "2026-05-10T10:00:11+00:00",
                "alert_type": "TEST",
                "severity": "low",
                "payload": {"score": 1},
            }

            store.bulk_upsert_raw_logs(records)
            store.insert_ingest_run(ingest_run)
            store.upsert_window_metrics(metrics)
            store.insert_alerts([alert])

            primary.fail_writes = False
            result = store.sync_fallback_to_primary()

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["pending_counts"]["raw_logs"], 0)
            self.assertEqual(result["pending_counts"]["ingest_runs"], 0)
            self.assertEqual(result["pending_counts"]["window_metrics"], 0)
            self.assertEqual(result["pending_counts"]["alerts_events"], 0)
            self.assertEqual(len(primary.raw_logs), 1)
            self.assertEqual(len(primary.ingest_runs), 1)
            self.assertEqual(len(primary.window_metrics), 1)
            self.assertEqual(len(primary.alerts), 1)

    def test_read_after_primary_recovery_auto_syncs_pending_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fallback = SqliteStore(str(Path(tmp_dir) / "fallback.db"))
            primary = FailingPrimaryStore()
            store = ResilientStore(primary=primary, fallback=fallback)
            store.ensure_schema()

            ingest_run = {
                "run_id": "run-1",
                "status": "success",
                "started_at_utc": "2026-05-10T10:00:00+00:00",
                "ended_at_utc": "2026-05-10T10:00:10+00:00",
                "duration_seconds": 10.0,
                "window_start": "2026-05-10T10:00:00+00:00",
                "window_end": "2026-05-10T10:30:00+00:00",
                "total_pages_expected": 1,
                "total_pages_fetched": 1,
                "total_records_info": 1,
                "total_records_fetched": 1,
                "error_message": None,
            }

            store.insert_ingest_run(ingest_run)
            self.assertEqual(store.get_fallback_status()["pending_counts"]["ingest_runs"], 1)

            primary.fail_writes = False
            runs = store.get_recent_ingest_runs(limit=10)
            fallback_status = store.get_fallback_status()

            self.assertEqual([run["run_id"] for run in runs], ["run-1"])
            self.assertEqual(fallback_status["pending_counts"]["ingest_runs"], 0)
            self.assertIsNotNone(fallback_status["last_fallback_sync_utc"])
            self.assertEqual(fallback_status["last_fallback_sync_result"]["status"], "ok")
            self.assertEqual(len(primary.ingest_runs), 1)

    def test_duplicate_fallback_records_do_not_duplicate_on_resync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fallback = SqliteStore(str(Path(tmp_dir) / "fallback.db"))
            primary = IdempotentPrimaryStore()
            store = ResilientStore(primary=primary, fallback=fallback)
            store.ensure_schema()

            record = {
                "_id": "log-1",
                "@timestamp": "2026-05-10T10:00:00+00:00",
                "is_llm_log": False,
                "is_system_log": True,
                "ingested_at": "2026-05-10T10:00:05+00:00",
            }
            ingest_run = {
                "run_id": "run-1",
                "status": "success",
                "started_at_utc": "2026-05-10T10:00:00+00:00",
                "ended_at_utc": "2026-05-10T10:00:10+00:00",
                "duration_seconds": 10.0,
                "window_start": "2026-05-10T10:00:00+00:00",
                "window_end": "2026-05-10T10:30:00+00:00",
                "total_pages_expected": 1,
                "total_pages_fetched": 1,
                "total_records_info": 1,
                "total_records_fetched": 1,
                "error_message": None,
            }
            metrics = {
                "window_key": "20260510T100000Z_20260510T103000Z",
                "run_id": "run-1",
                "window_start": "2026-05-10T10:00:00+00:00",
                "window_end": "2026-05-10T10:30:00+00:00",
                "total_records": 1,
                "threat_score": 0,
                "detection_count": 0,
                "attack_predicted": False,
                "model_available": False,
                "is_anomaly": False,
                "anomaly_score": 0.0,
                "anomaly_percentile": 0.0,
                "saved_at_utc": "2026-05-10T10:00:10+00:00",
            }
            alert = {
                "alert_id": "alert-1",
                "run_id": "run-1",
                "detected_at_utc": "2026-05-10T10:00:11+00:00",
                "alert_type": "TEST",
                "severity": "low",
                "payload": {"score": 1},
            }

            store.bulk_upsert_raw_logs([record])
            store.bulk_upsert_raw_logs([record])
            store.insert_ingest_run(ingest_run)
            store.insert_ingest_run(ingest_run)
            store.upsert_window_metrics(metrics)
            store.upsert_window_metrics(metrics)
            store.insert_alerts([alert])
            store.insert_alerts([alert])

            fallback_status = store.get_fallback_status()
            self.assertEqual(fallback_status["pending_counts"]["raw_logs"], 1)
            self.assertEqual(fallback_status["pending_counts"]["ingest_runs"], 1)
            self.assertEqual(fallback_status["pending_counts"]["window_metrics"], 1)
            self.assertEqual(fallback_status["pending_counts"]["alerts_events"], 1)

            primary.fail_writes = False
            first_result = store.sync_fallback_to_primary()
            second_result = store.sync_fallback_to_primary()

            self.assertEqual(first_result["pending_counts"]["raw_logs"], 0)
            self.assertEqual(second_result["pending_counts"]["raw_logs"], 0)
            self.assertEqual(len(primary.raw_logs), 1)
            self.assertEqual(len(primary.ingest_runs), 1)
            self.assertEqual(len(primary.window_metrics), 1)
            self.assertEqual(len(primary.alerts), 1)


if __name__ == "__main__":
    unittest.main()
