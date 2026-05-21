"""Extended tests for backend/api/http/application.py — target >= 70%."""
import unittest
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# FakeStore — same pattern as test_block_c_api.py
# ---------------------------------------------------------------------------

class FakeStore:
    def get_last_run(self):
        return {"run_id": "run-1", "status": "success", "started_at_utc": "2026-05-21T01:30:00+00:00",
                "ended_at_utc": "2026-05-21T01:45:00+00:00", "duration_seconds": 15.0}

    def get_latest_window_metrics(self):
        return {"window_key": "w1", "threat_score": 30, "is_anomaly": False,
                "risk_level": "novel_activity", "anomaly_reason": "first_observed_values",
                "total_records": 5000}

    def get_recent_alerts(self, limit=50):
        return [{"alert_id": "a1", "alert_type": "security_spike", "severity": "high",
                 "detected_at_utc": "2026-05-21T01:45:00Z", "run_id": "run-1", "payload": {}}]

    def get_recent_window_metrics(self, limit=50):
        return [{"window_key": "w1", "total_records": 5000, "threat_score": 30,
                 "is_anomaly": False, "risk_level": "novel_activity",
                 "anomaly_reason": "first_observed_values"}]

    def get_recent_ingest_runs(self, limit=20):
        return [{"run_id": "run-1", "status": "success", "started_at_utc": "2026-05-21T01:30:00Z"}]

    def get_dashboard_summary(self, time_window_hours=24):
        return {"total_alerts": 2, "alerts_by_severity": {"high": 1, "medium": 1},
                "top_metrics": {"threat_score": 30, "is_anomaly": False}, "last_run": {}}

    def get_recent_window_features(self, limit=200):
        return [{"window_key": "w1", "total_records": 5000}] * 12

    def get_fallback_status(self):
        return {"enabled": False}

    def get_pending_counts(self):
        return {}

    def sync_fallback_to_primary(self):
        return {"synced": True, "synced_counts": {}}

    def upsert_raw_logs(self, records): return len(records)
    def bulk_upsert_raw_logs(self, records, batch_size=1000): return len(records)
    def insert_ingest_run(self, run): pass
    def insert_alerts(self, alerts): return len(alerts)
    def upsert_window_metrics(self, m): pass
    def bulk_upsert_window_metrics(self, r, batch_size=1000): return len(r)
    def call_cleanup_procedure(self, retention_days=90):
        return {"status": "cleaned", "rows_deleted": 0, "deleted_counts": {},
                "retention_days": retention_days, "cutoff_utc": "2026-01-01"}
    def ensure_schema(self): pass


class FakeStoreWithFallback(FakeStore):
    def get_fallback_status(self):
        return {"enabled": True, "pending_counts": {"raw_logs": 0}}

    def sync_fallback_to_primary(self):
        return {"synced": True, "synced_counts": {"raw_logs": 5}}


# ---------------------------------------------------------------------------
# Helper to get TestClient
# ---------------------------------------------------------------------------

def _get_client(fake_store=None, storage_ready=True, admin_key="test-admin-key"):
    from fastapi.testclient import TestClient
    from backend.api.http.application import app
    fs = fake_store or FakeStore()
    storage_status = {"ready": storage_ready, "error": None if storage_ready else "db down"}
    with patch("backend.api.http.application.store", fs), \
         patch("backend.api.http.application._storage_status", storage_status), \
         patch("backend.api.http.application.settings") as mock_settings:
        mock_settings.admin_api_key = admin_key
        mock_settings.sap_soc_token = ""
        mock_settings.storage_backend = "sqlite"
        mock_settings.telegram_chatbot_enabled = True
        mock_settings.model_min_training_rows = 30
        mock_settings.model_history_limit = 200
        mock_settings.error_security_threshold = 25
        mock_settings.attack_score_threshold = 70
        mock_settings.model_enabled = False
        mock_settings.model_contamination = 0.1
        client = TestClient(app, raise_server_exceptions=False)
        yield client, fs, mock_settings


# ---------------------------------------------------------------------------
# Tests for /health/sap
# ---------------------------------------------------------------------------

class TestHealthSap(unittest.TestCase):

    def test_health_sap_success(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        mock_client = MagicMock()
        mock_client.get_health.return_value = {"status": "healthy"}
        with patch("backend.api.http.application.client", mock_client), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}):
            tc = TestClient(app)
            resp = tc.get("/health/sap")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "healthy")

    def test_health_sap_raises_502_on_error(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        mock_client = MagicMock()
        mock_client.get_health.side_effect = Exception("connection refused")
        with patch("backend.api.http.application.client", mock_client), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}):
            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get("/health/sap")
        self.assertEqual(resp.status_code, 502)


# ---------------------------------------------------------------------------
# Tests for /status/latest
# ---------------------------------------------------------------------------

class TestStatusLatest(unittest.TestCase):

    def test_status_latest_success(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        fs = FakeStore()
        with patch("backend.api.http.application.store", fs), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}):
            tc = TestClient(app)
            resp = tc.get("/status/latest")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)

    def test_status_latest_storage_not_ready(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"}), \
             patch("backend.api.http.application.settings") as ms:
            ms.storage_backend = "sqlite"
            tc = TestClient(app)
            resp = tc.get("/status/latest")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["storage_ready"], False)

    def test_status_latest_no_runs_yet(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app

        class EmptyStore(FakeStore):
            def get_last_run(self): return None

        with patch("backend.api.http.application.store", EmptyStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}):
            tc = TestClient(app)
            resp = tc.get("/status/latest")
        data = resp.json()
        self.assertEqual(data.get("status"), "no-runs-yet")

    def test_status_latest_with_fallback_enabled(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.store", FakeStoreWithFallback()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}):
            tc = TestClient(app)
            resp = tc.get("/status/latest")
        data = resp.json()
        # Should include fallback info when enabled
        self.assertIn("fallback", data)


# ---------------------------------------------------------------------------
# Tests for /history/status storage not ready
# ---------------------------------------------------------------------------

class TestHistoryStatusNotReady(unittest.TestCase):

    def test_returns_degraded_when_not_ready(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"}), \
             patch("backend.api.http.application.settings") as ms:
            ms.storage_backend = "sqlite"
            tc = TestClient(app)
            resp = tc.get("/history/status")
        data = resp.json()
        self.assertFalse(data["storage_ready"])

    def test_history_status_with_fallback(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.store", FakeStoreWithFallback()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.storage_backend = "hana"
            ms.model_min_training_rows = 30
            ms.model_history_limit = 200
            tc = TestClient(app)
            resp = tc.get("/history/status")
        data = resp.json()
        self.assertIn("fallback", data)


# ---------------------------------------------------------------------------
# Tests for storage-not-ready 503 responses
# ---------------------------------------------------------------------------

class TestStorageNotReady503(unittest.TestCase):

    def _not_ready_client(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        return TestClient(app, raise_server_exceptions=False), \
               patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"})

    def test_alerts_recent_503(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"}):
            resp = TestClient(app, raise_server_exceptions=False).get("/alerts/recent")
        self.assertEqual(resp.status_code, 503)

    def test_metrics_windows_503(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"}):
            resp = TestClient(app, raise_server_exceptions=False).get("/metrics/windows")
        self.assertEqual(resp.status_code, 503)

    def test_runs_recent_503(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"}):
            resp = TestClient(app, raise_server_exceptions=False).get("/runs/recent")
        self.assertEqual(resp.status_code, 503)

    def test_dashboard_503(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"}):
            resp = TestClient(app, raise_server_exceptions=False).get("/dashboard/summary")
        self.assertEqual(resp.status_code, 503)

    def test_run_ingestion_503(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"}):
            resp = TestClient(app, raise_server_exceptions=False).post("/run/ingestion")
        self.assertEqual(resp.status_code, 503)

    def test_reprocess_windows_503(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application._storage_status", {"ready": False, "error": "db down"}):
            resp = TestClient(app, raise_server_exceptions=False).post("/run/reprocess-windows")
        self.assertEqual(resp.status_code, 503)


# ---------------------------------------------------------------------------
# Tests for admin endpoints
# ---------------------------------------------------------------------------

class TestAdminEndpoints(unittest.TestCase):

    def _tc(self, fake_store=None):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        fs = fake_store or FakeStore()
        with patch("backend.api.http.application.store", fs), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.admin_api_key = "secret-key"
            ms.sap_soc_token = ""
            ms.storage_backend = "sqlite"
            yield TestClient(app, raise_server_exceptions=False)

    def test_cleanup_with_valid_token(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.store", FakeStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.admin_api_key = "secret"
            ms.sap_soc_token = ""
            tc = TestClient(app)
            resp = tc.post("/api/admin/cleanup",
                           json={"retention_days": 30},
                           headers={"x-api-key": "secret"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "cleaned")

    def test_cleanup_with_invalid_token_403(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.settings") as ms:
            ms.admin_api_key = "secret"
            ms.sap_soc_token = ""
            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.post("/api/admin/cleanup",
                           json={"retention_days": 30},
                           headers={"x-api-key": "wrong"})
        self.assertEqual(resp.status_code, 403)

    def test_cleanup_without_token_configured_503(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.settings") as ms:
            ms.admin_api_key = ""
            ms.sap_soc_token = ""
            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.post("/api/admin/cleanup", json={"retention_days": 30})
        self.assertEqual(resp.status_code, 503)

    def test_resync_fallback_not_enabled(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.store", FakeStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.admin_api_key = "secret"
            ms.sap_soc_token = ""
            tc = TestClient(app)
            resp = tc.post("/run/resync-fallback", headers={"x-api-key": "secret"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "not_enabled")

    def test_resync_fallback_enabled(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.store", FakeStoreWithFallback()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.admin_api_key = "secret"
            ms.sap_soc_token = ""
            tc = TestClient(app)
            resp = tc.post("/run/resync-fallback", headers={"x-api-key": "secret"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("synced"))

    def test_bearer_token_auth(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.store", FakeStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.admin_api_key = "bearer-secret"
            ms.sap_soc_token = ""
            tc = TestClient(app)
            resp = tc.post("/api/admin/cleanup",
                           json={"retention_days": 30},
                           headers={"Authorization": "Bearer bearer-secret"})
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Tests for /run/reprocess-windows
# ---------------------------------------------------------------------------

class TestReprocessWindows(unittest.TestCase):

    def test_reprocess_windows_happy_path(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.store", FakeStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.error_security_threshold = 25
            ms.attack_score_threshold = 70
            ms.model_min_training_rows = 30
            ms.model_history_limit = 200
            tc = TestClient(app)
            resp = tc.post("/run/reprocess-windows?limit=5&persist=false")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("processed_count", data)

    def test_reprocess_windows_with_persist(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        with patch("backend.api.http.application.store", FakeStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.error_security_threshold = 25
            ms.attack_score_threshold = 70
            ms.model_min_training_rows = 30
            ms.model_history_limit = 200
            tc = TestClient(app)
            resp = tc.post("/run/reprocess-windows?limit=1&persist=true")
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Tests for /run/ingestion
# ---------------------------------------------------------------------------

class TestRunIngestion(unittest.TestCase):

    def test_run_ingestion_calls_execute_cycle(self):
        from fastapi.testclient import TestClient
        from backend.api.http.application import app
        mock_result = {"status": "ok", "windows": [], "alerts": []}
        with patch("backend.api.http.application.store", FakeStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.execute_ingestion_cycle", return_value=mock_result):
            tc = TestClient(app)
            resp = tc.post("/run/ingestion")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


# ---------------------------------------------------------------------------
# Tests for helper functions
# ---------------------------------------------------------------------------

class TestFormatKvForTelegram(unittest.TestCase):

    def test_formats_dict_as_key_value(self):
        from backend.api.http.application import _format_kv_for_telegram
        result = _format_kv_for_telegram("Title", {"status": "ok", "count": 5})
        self.assertIn("Title", result)
        self.assertIn("Status: ok", result)
        self.assertIn("Count: 5", result)

    def test_empty_dict(self):
        from backend.api.http.application import _format_kv_for_telegram
        result = _format_kv_for_telegram("Title", {})
        self.assertEqual(result, "Title")


class TestExtractCommandArgument(unittest.TestCase):

    def test_extracts_argument(self):
        from backend.api.http.application import _extract_command_argument
        result = _extract_command_argument("/ask cuantas alertas?", "ask")
        self.assertEqual(result, "cuantas alertas?")

    def test_returns_empty_when_no_match(self):
        from backend.api.http.application import _extract_command_argument
        result = _extract_command_argument("random text", "ask")
        self.assertEqual(result, "")

    def test_handles_bot_mention(self):
        from backend.api.http.application import _extract_command_argument
        result = _extract_command_argument("/ask@mybot hello world", "ask")
        self.assertEqual(result, "hello world")

    def test_empty_argument(self):
        from backend.api.http.application import _extract_command_argument
        result = _extract_command_argument("/ask", "ask")
        self.assertEqual(result, "")


class TestContextCall(unittest.TestCase):

    def test_ok_when_builder_succeeds(self):
        from backend.api.http.application import _context_call
        result = _context_call("test", lambda: {"key": "value"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["key"], "value")

    def test_error_when_builder_raises(self):
        from backend.api.http.application import _context_call
        result = _context_call("test", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


class TestBuildChatbotContext(unittest.TestCase):

    def test_returns_expected_structure(self):
        from backend.api.http.application import _build_chatbot_context
        with patch("backend.api.http.application.store", FakeStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.model_min_training_rows = 30
            ms.model_history_limit = 200
            ms.storage_backend = "sqlite"
            ms.admin_api_key = ""
            result = _build_chatbot_context("cuantas alertas hay?")
        self.assertIn("summary", result)
        self.assertIn("endpoint_snapshots", result)
        self.assertIn("question", result)
        self.assertEqual(result["question"], "cuantas alertas hay?")

    def test_summary_contains_expected_fields(self):
        from backend.api.http.application import _build_chatbot_context
        with patch("backend.api.http.application.store", FakeStore()), \
             patch("backend.api.http.application._storage_status", {"ready": True, "error": None}), \
             patch("backend.api.http.application.settings") as ms:
            ms.model_min_training_rows = 30
            ms.model_history_limit = 200
            ms.storage_backend = "sqlite"
            ms.admin_api_key = ""
            result = _build_chatbot_context("q")
        summary = result["summary"]
        self.assertIn("recent_alerts", summary)
        self.assertIn("high_alerts", summary)
        self.assertIn("fallback_enabled", summary)


if __name__ == "__main__":
    unittest.main()
