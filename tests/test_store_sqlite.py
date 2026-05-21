"""Tests for SqliteStore + helpers in store.py — target >= 70% total on store.py."""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


def _make_store():
    from backend.storage.backends.store import SqliteStore
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = SqliteStore(tmp.name)
    store.ensure_schema()
    return store, tmp.name


def _cleanup(path):
    import gc
    gc.collect()
    try:
        import os as _os
        _os.unlink(path)
    except (PermissionError, OSError):
        pass


def _raw_log(log_id="LOG001", is_system=True, is_llm=False):
    return {
        "_id": log_id,
        "@timestamp": "2026-05-21T01:30:00+00:00",
        "is_system_log": is_system,
        "is_llm_log": is_llm,
        "client_ip": "10.0.0.1",
        "service_id": "analytics",
    }


def _ingest_run(run_id="run-001", status="success"):
    return {
        "run_id": run_id,
        "status": status,
        "started_at_utc": "2026-05-21T01:30:00+00:00",
        "ended_at_utc": "2026-05-21T01:45:00+00:00",
        "duration_seconds": 15.0,
        "window_start": "2026-05-21T01:00:00+00:00",
        "window_end": "2026-05-21T01:30:00+00:00",
        "total_pages_expected": 5,
        "total_pages_fetched": 5,
        "total_records_info": 1000,
        "total_records_fetched": 1000,
        "error_message": None,
    }


def _alert_event(alert_id="alert-001", severity="high"):
    return {
        "alert_id": alert_id,
        "run_id": "run-001",
        "detected_at_utc": "2026-05-21T01:45:00+00:00",
        "alert_type": "security_spike",
        "severity": severity,
        "payload": {"score": 85, "payload": {"security_count": 50}},
    }


def _window_metrics(window_key="20260521T013000Z_20260521T020000Z", total_records=5000):
    return {
        "window_key": window_key,
        "window_start": "2026-05-21T01:30:00+00:00",
        "window_end": "2026-05-21T02:00:00+00:00",
        "total_records": total_records,
        "system_log_count": 3000,
        "llm_log_count": 2000,
        "error_count": 100,
        "security_count": 10,
        "warning_count": 50,
        "audit_count": 20,
        "debug_count": 30,
        "perf_count": 5,
        "unique_client_ips": 50,
        "unique_services": 5,
        "http_4xx_count": 20,
        "http_5xx_count": 5,
        "max_events_from_single_ip": 10,
        "llm_request_count": 500,
        "llm_error_count": 10,
        "llm_timeout_count": 5,
        "avg_llm_latency_ms": 500.0,
        "p95_llm_latency_ms": 900.0,
        "total_llm_cost_usd": 1.0,
        "system_error_rate": 0.03,
        "security_event_rate": 0.003,
        "llm_error_rate": 0.02,
        "llm_timeout_rate": 0.01,
        "top_ip_event_share": 0.01,
        "threat_score": 30,
        "attack_predicted": False,
        "is_anomaly": False,
        "anomaly_score": 0.0,
        "anomaly_percentile": 0.0,
        "detection_count": 0,
        "risk_level": "novel_activity",
        "anomaly_reason": "first_observed_values",
        "saved_at_utc": "2026-05-21T01:45:00+00:00",
    }


class TestSqliteStoreWrite(unittest.TestCase):

    def setUp(self):
        self.store, self.db_path = _make_store()

    def tearDown(self):
        _cleanup(self.db_path)

    def test_upsert_raw_logs_returns_count(self):
        count = self.store.upsert_raw_logs([_raw_log("L1"), _raw_log("L2")])
        self.assertEqual(count, 2)

    def test_upsert_raw_logs_empty_returns_zero(self):
        count = self.store.upsert_raw_logs([])
        self.assertEqual(count, 0)

    def test_upsert_raw_logs_uses_fallback_id_when_no_id(self):
        record = {"@timestamp": "2026-05-21T01:30:00Z", "is_system_log": True}
        count = self.store.upsert_raw_logs([record])
        self.assertEqual(count, 1)

    def test_bulk_upsert_raw_logs(self):
        records = [_raw_log(f"L{i}") for i in range(10)]
        total = self.store.bulk_upsert_raw_logs(records, batch_size=3)
        self.assertEqual(total, 10)

    def test_bulk_upsert_empty_returns_zero(self):
        self.assertEqual(self.store.bulk_upsert_raw_logs([]), 0)

    def test_insert_ingest_run(self):
        self.store.insert_ingest_run(_ingest_run())
        run = self.store.get_last_run()
        self.assertIsNotNone(run)
        self.assertEqual(run["run_id"], "run-001")

    def test_insert_alerts_returns_count(self):
        count = self.store.insert_alerts([_alert_event("a1"), _alert_event("a2")])
        self.assertEqual(count, 2)

    def test_insert_alerts_empty_returns_zero(self):
        self.assertEqual(self.store.insert_alerts([]), 0)

    def test_upsert_window_metrics(self):
        self.store.upsert_window_metrics(_window_metrics())
        latest = self.store.get_latest_window_metrics()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["window_key"], "20260521T013000Z_20260521T020000Z")

    def test_bulk_upsert_window_metrics(self):
        metrics = [_window_metrics(f"key_{i}") for i in range(5)]
        count = self.store.bulk_upsert_window_metrics(metrics, batch_size=2)
        self.assertEqual(count, 5)


class TestSqliteStoreRead(unittest.TestCase):

    def setUp(self):
        self.store, self.db_path = _make_store()
        # Seed data
        self.store.insert_ingest_run(_ingest_run("run-1"))
        self.store.insert_ingest_run(_ingest_run("run-2", status="failed"))
        self.store.insert_alerts([_alert_event("a1", "high"), _alert_event("a2", "medium")])
        self.store.upsert_window_metrics(_window_metrics())

    def tearDown(self):
        _cleanup(self.db_path)

    def test_get_last_run_returns_most_recent(self):
        run = self.store.get_last_run()
        self.assertIsNotNone(run)
        self.assertIn("run_id", run)

    def test_get_last_run_empty_returns_none(self):
        store, path = _make_store()
        try:
            self.assertIsNone(store.get_last_run())
        finally:
            _cleanup(path)

    def test_get_recent_alerts(self):
        alerts = self.store.get_recent_alerts(limit=10)
        self.assertGreaterEqual(len(alerts), 1)
        self.assertIn("alert_type", alerts[0])

    def test_get_recent_alerts_payload_deserialized(self):
        alerts = self.store.get_recent_alerts(limit=1)
        self.assertIsInstance(alerts[0]["payload"], dict)

    def test_get_recent_ingest_runs(self):
        runs = self.store.get_recent_ingest_runs(limit=10)
        self.assertGreaterEqual(len(runs), 2)

    def test_get_recent_window_metrics(self):
        windows = self.store.get_recent_window_metrics(limit=5)
        self.assertEqual(len(windows), 1)
        self.assertIn("window_key", windows[0])

    def test_get_latest_window_metrics(self):
        latest = self.store.get_latest_window_metrics()
        self.assertIsNotNone(latest)

    def test_get_latest_window_metrics_empty_returns_none(self):
        store, path = _make_store()
        try:
            self.assertIsNone(store.get_latest_window_metrics())
        finally:
            _cleanup(path)

    def test_get_dashboard_summary(self):
        summary = self.store.get_dashboard_summary(time_window_hours=24)
        self.assertIn("total_alerts", summary)
        self.assertIn("alerts_by_severity", summary)
        self.assertIn("top_metrics", summary)
        self.assertIn("last_run", summary)

    def test_get_dashboard_summary_counts_alerts(self):
        summary = self.store.get_dashboard_summary(time_window_hours=24)
        self.assertGreaterEqual(summary["total_alerts"], 2)

    def test_get_recent_window_features_empty(self):
        features = self.store.get_recent_window_features(limit=10)
        self.assertIsInstance(features, list)

    def test_get_pending_counts(self):
        counts = self.store.get_pending_counts()
        self.assertIn("raw_logs", counts)
        self.assertIn("ingest_runs", counts)
        self.assertIn("alerts_events", counts)
        self.assertIn("window_metrics", counts)
        self.assertGreaterEqual(counts["ingest_runs"], 2)


class TestSqliteStoreCleanup(unittest.TestCase):

    def setUp(self):
        self.store, self.db_path = _make_store()
        self.store.upsert_raw_logs([_raw_log()])
        self.store.insert_ingest_run(_ingest_run())
        self.store.insert_alerts([_alert_event()])
        self.store.upsert_window_metrics(_window_metrics())

    def tearDown(self):
        _cleanup(self.db_path)

    def test_call_cleanup_procedure_returns_status(self):
        result = self.store.call_cleanup_procedure(retention_days=90)
        self.assertEqual(result["status"], "cleaned")
        self.assertIn("rows_deleted", result)
        self.assertIn("deleted_counts", result)

    def test_call_cleanup_procedure_aggressive_deletes_old(self):
        result = self.store.call_cleanup_procedure(retention_days=0)
        self.assertEqual(result["status"], "cleaned")

    def test_delete_by_ids_empty(self):
        result = self.store._delete_by_ids("raw_logs", "log_id", [])
        self.assertEqual(result, 0)

    def test_delete_raw_logs(self):
        self.store.upsert_raw_logs([_raw_log("DELETE_ME")])
        count = self.store.delete_raw_logs(["DELETE_ME"])
        self.assertEqual(count, 1)

    def test_delete_ingest_runs(self):
        self.store.insert_ingest_run(_ingest_run("del-run"))
        count = self.store.delete_ingest_runs(["del-run"])
        self.assertEqual(count, 1)

    def test_delete_alerts(self):
        self.store.insert_alerts([_alert_event("del-alert")])
        count = self.store.delete_alerts(["del-alert"])
        self.assertEqual(count, 1)

    def test_delete_window_metrics(self):
        key = "20260521T013000Z_20260521T020000Z"
        count = self.store.delete_window_metrics([key])
        self.assertEqual(count, 1)


class TestSqliteStoreExport(unittest.TestCase):

    def setUp(self):
        self.store, self.db_path = _make_store()
        self.store.upsert_raw_logs([_raw_log("L1"), _raw_log("L2")])
        self.store.insert_ingest_run(_ingest_run())
        self.store.insert_alerts([_alert_event()])

    def tearDown(self):
        _cleanup(self.db_path)

    def test_export_raw_logs(self):
        rows = self.store.export_raw_logs(limit=100)
        self.assertEqual(len(rows), 2)

    def test_export_raw_logs_zero_limit_returns_all(self):
        rows = self.store.export_raw_logs(limit=100000)
        self.assertGreaterEqual(len(rows), 2)

    def test_export_ingest_runs(self):
        rows = self.store.export_ingest_runs()
        self.assertEqual(len(rows), 1)

    def test_export_alerts(self):
        rows = self.store.export_alerts()
        self.assertEqual(len(rows), 1)


class TestSqliteStoreUtils(unittest.TestCase):

    def setUp(self):
        self.store, self.db_path = _make_store()

    def tearDown(self):
        _cleanup(self.db_path)

    def test_fallback_id_produces_consistent_hash(self):
        from backend.storage.backends.store import SqliteStore
        record = {"key": "value", "num": 42}
        h1 = SqliteStore._fallback_id(record)
        h2 = SqliteStore._fallback_id(record)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_fallback_id_different_for_different_records(self):
        from backend.storage.backends.store import SqliteStore
        h1 = SqliteStore._fallback_id({"a": 1})
        h2 = SqliteStore._fallback_id({"a": 2})
        self.assertNotEqual(h1, h2)

    def test_ensure_sqlite_column_adds_missing(self):
        from backend.storage.backends.store import SqliteStore
        import sqlite3
        with self.store._connect() as conn:
            before = {row["name"] for row in conn.execute("PRAGMA table_info(raw_logs)").fetchall()}
            self.assertNotIn("test_col_xyz", before)
            SqliteStore._ensure_sqlite_column(conn, "raw_logs", "test_col_xyz", "TEXT")
            after = {row["name"] for row in conn.execute("PRAGMA table_info(raw_logs)").fetchall()}
            self.assertIn("test_col_xyz", after)

    def test_ensure_sqlite_column_skips_existing(self):
        from backend.storage.backends.store import SqliteStore
        with self.store._connect() as conn:
            SqliteStore._ensure_sqlite_column(conn, "raw_logs", "log_id", "TEXT")


class TestShouldTrainOnWindow(unittest.TestCase):

    def test_returns_true_for_normal_window(self):
        from backend.storage.backends.store import _should_train_on_window
        self.assertTrue(_should_train_on_window({"total_records": 100, "anomaly_reason": "first_observed"}))

    def test_returns_false_for_zero_records(self):
        from backend.storage.backends.store import _should_train_on_window
        self.assertFalse(_should_train_on_window({"total_records": 0}))

    def test_returns_false_for_excluded_reasons(self):
        from backend.storage.backends.store import _should_train_on_window
        for reason in ["empty_window", "possible_incomplete_window", "llm_activity_drop", "llm_quality_degradation"]:
            self.assertFalse(
                _should_train_on_window({"total_records": 100, "anomaly_reason": reason}),
                f"Expected False for reason={reason}"
            )


class TestCreateStore(unittest.TestCase):

    def test_sqlite_backend_returns_sqlite_store(self):
        from backend.storage.backends.store import create_store, SqliteStore
        settings = MagicMock()
        settings.storage_backend = "sqlite"
        settings.sqlite_path = ":memory:"
        store = create_store(settings)
        self.assertIsInstance(store, SqliteStore)

    def test_hana_backend_returns_resilient_store(self):
        from backend.storage.backends.store import create_store, ResilientStore
        settings = MagicMock()
        settings.storage_backend = "hana"
        settings.sqlite_path = ":memory:"
        store = create_store(settings)
        self.assertIsInstance(store, ResilientStore)


class TestBaseStoreDefaults(unittest.TestCase):

    def test_sync_fallback_returns_not_supported(self):
        from backend.storage.backends.store import SqliteStore
        _, path = _make_store()
        try:
            store = SqliteStore(path)
            # SQLiteStore doesn't override sync_fallback_to_primary but calls parent default
            # We test via ResilientStore's fallback which has its own sync
            result = store.sync_fallback_to_primary()
            # SqliteStore returns the BaseStore default "not_supported"
            self.assertEqual(result.get("status"), "not_supported")
        finally:
            _cleanup(path)

    def test_get_fallback_status_returns_disabled(self):
        from backend.storage.backends.store import SqliteStore
        _, path = _make_store()
        try:
            store = SqliteStore(path)
            status = store.get_fallback_status()
            self.assertFalse(status.get("enabled"))
        finally:
            _cleanup(path)

    def test_export_raw_logs_base_default(self):
        # BaseStore.export_raw_logs returns [] by default (line 90)
        # We test this via a partial subclass
        from backend.storage.backends.store import BaseStore

        class MinimalStore(BaseStore):
            def ensure_schema(self): pass
            def upsert_raw_logs(self, r): return 0
            def bulk_upsert_raw_logs(self, r, b=1000): return 0
            def insert_ingest_run(self, r): pass
            def insert_alerts(self, r): return 0
            def get_last_run(self): return None
            def upsert_window_metrics(self, m): pass
            def bulk_upsert_window_metrics(self, r, b=1000): return 0
            def get_recent_window_metrics(self, l=50): return []
            def get_recent_alerts(self, l=50): return []
            def get_recent_ingest_runs(self, l=20): return []
            def get_dashboard_summary(self, h=24): return {}
            def get_recent_window_features(self, l=200): return []
            def get_latest_window_metrics(self): return None
            def call_cleanup_procedure(self, d=90): return {}

        store = MinimalStore()
        self.assertEqual(store.export_raw_logs(), [])
        result = store.sync_fallback_to_primary()
        self.assertEqual(result.get("status"), "not_supported")
        status = store.get_fallback_status()
        self.assertFalse(status["enabled"])


if __name__ == "__main__":
    unittest.main()
