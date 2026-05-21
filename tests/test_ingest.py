"""Tests for backend/services/ingestion/ingest.py — target >= 70%."""
import unittest
from unittest.mock import MagicMock, patch


def _make_client(total_pages=2, records=None):
    client = MagicMock()
    info = {"total_pages": total_pages, "total_records": len(records or []),
            "window_start": "2026-05-21T01:30:00+00:00", "window_end": "2026-05-21T02:00:00+00:00"}
    client.fetch_current_window_all_pages.return_value = {
        "info": info,
        "pages": [{}] * total_pages,
        "records": records or [{"id": i} for i in range(10)],
    }
    return client


class TestIngestRunResult(unittest.TestCase):

    def test_run_id_stored(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        client = _make_client()
        result, records = run_ingestion_cycle(client, run_id="run-abc")
        self.assertEqual(result.run_id, "run-abc")

    def test_success_status(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        client = _make_client(records=[{"id": 1}, {"id": 2}])
        result, records = run_ingestion_cycle(client, run_id="r1")
        self.assertEqual(result.status, "success")

    def test_records_returned_on_success(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        client = _make_client(records=[{"id": 1}, {"id": 2}, {"id": 3}])
        result, records = run_ingestion_cycle(client, run_id="r1")
        self.assertEqual(len(records), 3)
        self.assertEqual(result.total_records_fetched, 3)

    def test_pages_counted(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        client = _make_client(total_pages=5, records=[])
        result, _ = run_ingestion_cycle(client, run_id="r1")
        self.assertEqual(result.total_pages_expected, 5)
        self.assertEqual(result.total_pages_fetched, 5)

    def test_window_start_end_extracted(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        client = _make_client()
        result, _ = run_ingestion_cycle(client, run_id="r1")
        self.assertIsNotNone(result.window_start)
        self.assertIsNotNone(result.window_end)

    def test_error_message_is_none_on_success(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        result, _ = run_ingestion_cycle(_make_client(), run_id="r1")
        self.assertIsNone(result.error_message)

    def test_duration_is_positive(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        result, _ = run_ingestion_cycle(_make_client(), run_id="r1")
        self.assertGreaterEqual(result.duration_seconds, 0)


class TestRunIngestionCycleError(unittest.TestCase):

    def test_client_exception_returns_failed_status(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        client = MagicMock()
        client.fetch_current_window_all_pages.side_effect = RuntimeError("network down")
        result, records = run_ingestion_cycle(client, run_id="r1")
        self.assertEqual(result.status, "failed")
        self.assertEqual(records, [])

    def test_error_message_set_on_failure(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        client = MagicMock()
        client.fetch_current_window_all_pages.side_effect = Exception("timeout")
        result, _ = run_ingestion_cycle(client, run_id="r1")
        self.assertIn("timeout", result.error_message)

    def test_failed_result_has_zero_counts(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle
        client = MagicMock()
        client.fetch_current_window_all_pages.side_effect = Exception("boom")
        result, _ = run_ingestion_cycle(client, run_id="r1")
        self.assertEqual(result.total_records_fetched, 0)
        self.assertEqual(result.total_pages_fetched, 0)
        self.assertIsNone(result.window_start)


class TestIngestResultToDict(unittest.TestCase):

    def test_converts_to_dict(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle, ingest_result_to_dict
        result, _ = run_ingestion_cycle(_make_client(), run_id="r1")
        d = ingest_result_to_dict(result)
        self.assertIsInstance(d, dict)
        self.assertIn("run_id", d)
        self.assertIn("status", d)

    def test_all_fields_present(self):
        from backend.services.ingestion.ingest import run_ingestion_cycle, ingest_result_to_dict
        result, _ = run_ingestion_cycle(_make_client(), run_id="r1")
        d = ingest_result_to_dict(result)
        expected_fields = [
            "run_id", "status", "started_at_utc", "ended_at_utc",
            "duration_seconds", "window_start", "window_end",
            "total_pages_expected", "total_pages_fetched",
            "total_records_info", "total_records_fetched", "error_message",
        ]
        for field in expected_fields:
            self.assertIn(field, d, f"Missing field: {field}")


class TestUtcNowIso(unittest.TestCase):

    def test_returns_iso_string(self):
        from backend.services.ingestion.ingest import _utc_now_iso
        result = _utc_now_iso()
        self.assertIsInstance(result, str)
        self.assertIn("2026", result)


if __name__ == "__main__":
    unittest.main()
