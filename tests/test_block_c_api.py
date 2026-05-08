from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.api.http.application as application


class FakeStore:
    def ensure_schema(self) -> None:
        return None

    def get_recent_alerts(self, limit: int = 200):
        return [
            {
                "alert_id": "a-1",
                "run_id": "r-1",
                "detected_at_utc": "2026-05-02T10:00:00Z",
                "alert_type": "security",
                "severity": "high",
                "payload": {"kind": "security", "count": 3},
            },
            {
                "alert_id": "a-2",
                "run_id": "r-2",
                "detected_at_utc": "2026-05-02T09:30:00Z",
                "alert_type": "llm",
                "severity": "medium",
                "payload": {"kind": "llm", "count": 1},
            },
        ][:limit]

    def get_recent_window_metrics(self, limit: int = 200):
        return [
            {
                "window_key": "20260502T100000Z_20260502T103000Z",
                "window_start": "2026-05-02T10:00:00Z",
                "window_end": "2026-05-02T10:30:00Z",
                "total_records": 120,
                "threat_score": 80,
                "attack_predicted": True,
                "model_available": False,
                "is_anomaly": True,
                "anomaly_score": 0.91,
                "anomaly_percentile": 99.0,
                "saved_at_utc": "2026-05-02T10:31:00Z",
            }
        ][:limit]

    def get_recent_ingest_runs(self, limit: int = 200):
        return [
            {
                "run_id": "r-1",
                "status": "success",
                "started_at_utc": "2026-05-02T10:00:00Z",
                "ended_at_utc": "2026-05-02T10:01:00Z",
                "duration_seconds": 60.0,
                "window_start": "2026-05-02T10:00:00Z",
                "window_end": "2026-05-02T10:30:00Z",
                "total_pages_expected": 1,
                "total_pages_fetched": 1,
                "total_records_info": 120,
                "total_records_fetched": 120,
                "error_message": None,
            }
        ][:limit]

    def get_last_run(self):
        return self.get_recent_ingest_runs(limit=1)[0]

    def get_latest_window_metrics(self):
        return self.get_recent_window_metrics(limit=1)[0]

    def bulk_upsert_raw_logs(self, records, batch_size: int = 1000):
        return len(records)

    def bulk_upsert_window_metrics(self, records, batch_size: int = 1000):
        return len(records)

    def insert_ingest_run(self, ingest_run):
        return None

    def insert_alerts(self, alerts):
        return len(alerts)

    def upsert_raw_logs(self, records):
        return len(records)

    def upsert_window_metrics(self, metrics):
        return None

    def call_cleanup_procedure(self, retention_days: int = 90):
        return {"status": "cleaned", "retention_days": retention_days, "rows_deleted": 0, "deleted_counts": {}}

    def get_recent_window_features(self, limit: int = 200):
        return []

    def get_dashboard_summary(self, time_window_hours: int = 24):
        return {
            "total_alerts": 2,
            "alerts_by_severity": {"high": 1, "medium": 1},
            "top_metrics": {
                "window_key": "20260502T100000Z_20260502T103000Z",
                "threat_score": 80,
                "is_anomaly": True,
            },
            "last_run": {
                "run_id": "r-1",
                "status": "success",
                "duration_seconds": 60.0,
                "error_message": None,
            },
            "generated_at": "2026-05-02T10:31:00Z",
        }


class BlockCApiTests(unittest.TestCase):
    def test_recent_alerts_windows_and_runs_endpoints(self) -> None:
        fake_store = FakeStore()
        with patch.object(application, "store", fake_store), patch.object(
            application, "_storage_status", {"ready": True, "error": None}
        ):
            with TestClient(application.app) as client:
                alerts_response = client.get("/alerts/recent?limit=2")
                self.assertEqual(alerts_response.status_code, 200)
                alerts = alerts_response.json()
                self.assertEqual(len(alerts), 2)
                self.assertEqual(alerts[0]["alert_id"], "a-1")
                self.assertEqual(alerts[0]["payload"]["kind"], "security")

                windows_response = client.get("/metrics/windows?limit=1")
                self.assertEqual(windows_response.status_code, 200)
                windows = windows_response.json()
                self.assertEqual(len(windows), 1)
                self.assertEqual(windows[0]["window_key"], "20260502T100000Z_20260502T103000Z")
                self.assertTrue(windows[0]["is_anomaly"])

                runs_response = client.get("/runs/recent?limit=1")
                self.assertEqual(runs_response.status_code, 200)
                runs = runs_response.json()
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0]["run_id"], "r-1")
                self.assertEqual(runs[0]["status"], "success")

    def test_dashboard_summary_endpoint(self) -> None:
        fake_store = FakeStore()
        with patch.object(application, "store", fake_store), patch.object(
            application, "_storage_status", {"ready": True, "error": None}
        ):
            with TestClient(application.app) as client:
                response = client.get("/dashboard/summary?time_window_hours=24")
                self.assertEqual(response.status_code, 200)
                dashboard = response.json()
                
                # Verify structure
                self.assertIn("total_alerts", dashboard)
                self.assertIn("alerts_by_severity", dashboard)
                self.assertIn("top_metrics", dashboard)
                self.assertIn("last_run", dashboard)
                self.assertIn("generated_at", dashboard)
                
                # Verify data
                self.assertEqual(dashboard["total_alerts"], 2)
                self.assertEqual(dashboard["alerts_by_severity"]["high"], 1)
                self.assertEqual(dashboard["top_metrics"]["threat_score"], 80)
                self.assertEqual(dashboard["last_run"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
