from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.config import load_settings
from backend.storage.backends.store import HanaStore


class BlockCHanaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = load_settings()
        if not settings.hana_host or not settings.hana_user or not settings.hana_password:
            raise unittest.SkipTest("HANA credentials are not configured")

        cls.settings = settings
        cls.store = HanaStore(settings)
        cls.store.ensure_schema()

    def setUp(self) -> None:
        self.test_run_id = f"it-run-{uuid4().hex}"
        self.test_alert_id = f"it-alert-{uuid4().hex}"
        self.test_window_key = f"it-window-{uuid4().hex}"

    def tearDown(self) -> None:
        schema = self.settings.hana_schema
        with self.store._connection() as conn:  # type: ignore[attr-defined]
            cursor = conn.cursor()
            cursor.execute(
                f'DELETE FROM "{schema}"."ALERTS_EVENTS" WHERE ALERT_ID = ?',
                (self.test_alert_id,),
            )
            cursor.execute(
                f'DELETE FROM "{schema}"."WINDOW_METRICS" WHERE WINDOW_KEY = ?',
                (self.test_window_key,),
            )
            cursor.execute(
                f'DELETE FROM "{schema}"."WINDOW_FEATURES" WHERE WINDOW_KEY = ?',
                (self.test_window_key,),
            )
            cursor.execute(
                f'DELETE FROM "{schema}"."INGEST_RUNS" WHERE RUN_ID = ?',
                (self.test_run_id,),
            )
            conn.commit()

    def _seed_block_c_records(self) -> None:
        now = datetime.utcnow().replace(microsecond=0)
        start = now - timedelta(minutes=5)

        self.store.insert_ingest_run(
            {
                "run_id": self.test_run_id,
                "status": "success",
                "started_at_utc": start.isoformat(),
                "ended_at_utc": now.isoformat(),
                "duration_seconds": 300.0,
                "window_start": start.isoformat(),
                "window_end": now.isoformat(),
                "total_pages_expected": 1,
                "total_pages_fetched": 1,
                "total_records_info": 10,
                "total_records_fetched": 10,
                "error_message": None,
            }
        )

        self.store.insert_alerts(
            [
                {
                    "alert_id": self.test_alert_id,
                    "run_id": self.test_run_id,
                    "detected_at_utc": now.isoformat(),
                    "alert_type": "security",
                    "severity": "high",
                    "payload": {"source": "integration-test", "count": 1},
                }
            ]
        )

        self.store.upsert_window_metrics(
            {
                "window_key": self.test_window_key,
                "run_id": self.test_run_id,
                "window_start": start.isoformat(),
                "window_end": now.isoformat(),
                "total_records": 10,
                "threat_score": 85,
                "detection_count": 1,
                "attack_predicted": True,
                "model_available": True,
                "is_anomaly": False,
                "anomaly_score": 0.1,
                "anomaly_percentile": 0.6,
                "summary_json": "",
                "saved_at_utc": now.isoformat(),
            }
        )

    def test_recent_queries_return_seeded_data(self) -> None:
        self._seed_block_c_records()

        alerts = self.store.get_recent_alerts(limit=50)
        runs = self.store.get_recent_ingest_runs(limit=50)
        windows = self.store.get_recent_window_metrics(limit=50)

        self.assertTrue(any(item.get("alert_id") == self.test_alert_id for item in alerts))
        self.assertTrue(any(item.get("run_id") == self.test_run_id for item in runs))
        self.assertTrue(any(item.get("window_key") == self.test_window_key for item in windows))

    def test_dashboard_summary_returns_expected_shape(self) -> None:
        self._seed_block_c_records()

        summary = self.store.get_dashboard_summary(time_window_hours=24)

        self.assertIn("total_alerts", summary)
        self.assertIn("alerts_by_severity", summary)
        self.assertIn("top_metrics", summary)
        self.assertIn("last_run", summary)
        self.assertIn("generated_at", summary)

        self.assertIsInstance(summary["alerts_by_severity"], dict)
        self.assertIsInstance(summary["top_metrics"], dict)
        self.assertIsInstance(summary["last_run"], dict)


if __name__ == "__main__":
    unittest.main()
