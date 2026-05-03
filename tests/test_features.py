from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.services.ingestion.features import build_window_drilldown, build_window_metrics
from backend.services.ingestion.normalize import normalize_records
from backend.storage.backends.store import SqliteStore


class IngestionFeatureTests(unittest.TestCase):
    def test_normalize_records_marks_llm_and_system_logs(self) -> None:
        records = [
            {"_id": "1", "sap_function_log_type": "llm_timeout"},
            {"_id": "2", "sap_function_log_type": "ERROR"},
        ]

        normalized = normalize_records(records)

        self.assertTrue(normalized[0]["is_llm_log"])
        self.assertFalse(normalized[0]["is_system_log"])
        self.assertFalse(normalized[1]["is_llm_log"])
        self.assertTrue(normalized[1]["is_system_log"])
        self.assertIn("ingested_at", normalized[0])

    def test_build_window_metrics_aggregates_security_and_llm_signals(self) -> None:
        normalized = normalize_records(
            [
                {
                    "_id": "1",
                    "sap_function_log_type": "ERROR",
                    "client_ip": "10.0.0.1",
                    "service_id": "svc-a",
                    "http_status_code": 500,
                },
                {
                    "_id": "2",
                    "sap_function_log_type": "SECURITY",
                    "client_ip": "10.0.0.1",
                    "service_id": "svc-b",
                    "http_status_code": 403,
                },
                {
                    "_id": "3",
                    "sap_function_log_type": "LLM_TIMEOUT",
                    "llm_model_id": "gpt-4.1",
                    "llm_response_time_ms": 3100,
                    "llm_cost_usd": 0.42,
                },
            ]
        )

        metrics = build_window_metrics(
            normalized_records=normalized,
            window_start="2026-04-25T10:00:00+00:00",
            window_end="2026-04-25T10:30:00+00:00",
        )

        self.assertEqual(metrics["total_records"], 3)
        self.assertEqual(metrics["system_log_count"], 2)
        self.assertEqual(metrics["llm_log_count"], 1)
        self.assertEqual(metrics["error_count"], 1)
        self.assertEqual(metrics["security_count"], 1)
        self.assertEqual(metrics["http_4xx_count"], 1)
        self.assertEqual(metrics["http_5xx_count"], 1)
        self.assertEqual(metrics["unique_client_ips"], 1)
        self.assertEqual(metrics["unique_services"], 2)
        self.assertEqual(metrics["llm_timeout_count"], 1)
        self.assertEqual(metrics["avg_llm_latency_ms"], 3100)
        self.assertAlmostEqual(metrics["total_llm_cost_usd"], 0.42)

    def test_build_window_drilldown_collects_security_evidence(self) -> None:
        normalized = normalize_records(
            [
                {
                    "_id": "1",
                    "sap_function_log_type": "SECURITY",
                    "client_ip": "10.0.0.1",
                    "service_id": "svc-a",
                    "http_status_code": 403,
                },
                {
                    "_id": "2",
                    "sap_function_log_type": "SECURITY",
                    "client_ip": "10.0.0.1",
                    "service_id": "svc-b",
                    "http_status_code": 401,
                },
                {
                    "_id": "3",
                    "sap_function_log_type": "ERROR",
                    "client_ip": "10.0.0.2",
                    "service_id": "svc-a",
                    "http_status_code": 500,
                },
            ]
        )

        drilldown = build_window_drilldown(normalized)

        self.assertEqual(drilldown["top_log_types"][0]["value"], "SECURITY")
        self.assertEqual(drilldown["top_security_client_ips"][0]["value"], "10.0.0.1")
        self.assertEqual(drilldown["top_security_client_ips"][0]["count"], 2)
        self.assertEqual(drilldown["top_services"][0]["value"], "svc-a")

    def test_sqlite_store_persists_run_id_and_detection_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SqliteStore(str(Path(tmp_dir) / "pipeline.db"))
            store.ensure_schema()

            store.upsert_window_metrics(
                {
                    "window_key": "w1",
                    "run_id": "r1",
                    "window_start": "2026-04-25T10:00:00+00:00",
                    "window_end": "2026-04-25T10:30:00+00:00",
                    "total_records": 1,
                    "threat_score": 80,
                    "detection_count": 2,
                    "attack_predicted": True,
                    "model_available": True,
                    "is_anomaly": True,
                    "anomaly_score": 99.0,
                    "anomaly_percentile": 100.0,
                    "saved_at_utc": "2026-04-25T10:30:00+00:00",
                }
            )

            latest = store.get_latest_window_metrics()

        self.assertIsNotNone(latest)
        self.assertEqual(latest["run_id"], "r1")
        self.assertEqual(latest["detection_count"], 2)

    def test_sqlite_store_excludes_incomplete_windows_from_training_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SqliteStore(str(Path(tmp_dir) / "pipeline.db"))
            store.ensure_schema()

            base_metrics = {
                "window_key": "w1",
                "run_id": "r1",
                "window_start": "2026-04-25T10:00:00+00:00",
                "window_end": "2026-04-25T10:30:00+00:00",
                "total_records": 100,
                "threat_score": 0,
                "detection_count": 0,
                "attack_predicted": False,
                "model_available": False,
                "is_anomaly": False,
                "anomaly_score": 0.0,
                "anomaly_percentile": 0.0,
                "saved_at_utc": "2026-04-25T10:30:00+00:00",
            }

            store.upsert_window_metrics(base_metrics)
            store.upsert_window_metrics(
                {
                    **base_metrics,
                    "anomaly_reason": "possible_incomplete_window",
                    "risk_level": "data_quality",
                }
            )
            store.upsert_window_metrics(
                {
                    **base_metrics,
                    "window_key": "w2",
                    "anomaly_reason": "llm_activity_drop",
                    "risk_level": "service_activity_anomaly",
                }
            )
            store.upsert_window_metrics(
                {
                    **base_metrics,
                    "window_key": "w3",
                    "anomaly_reason": "system_activity_drop",
                    "risk_level": "service_activity_anomaly",
                }
            )

            features = store.get_recent_window_features()

        self.assertEqual(features, [])


if __name__ == "__main__":
    unittest.main()
