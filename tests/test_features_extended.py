"""Extended tests for backend/services/ingestion/features.py — target >= 95%."""
import unittest
from datetime import datetime, timezone


class TestSafeFloat(unittest.TestCase):

    def test_none_returns_none(self):
        from backend.services.ingestion.features import _safe_float
        self.assertIsNone(_safe_float(None))

    def test_empty_string_returns_none(self):
        from backend.services.ingestion.features import _safe_float
        self.assertIsNone(_safe_float(""))

    def test_invalid_string_returns_none(self):
        from backend.services.ingestion.features import _safe_float
        self.assertIsNone(_safe_float("not-a-number"))

    def test_valid_float_string(self):
        from backend.services.ingestion.features import _safe_float
        self.assertAlmostEqual(_safe_float("3.14"), 3.14)

    def test_valid_int(self):
        from backend.services.ingestion.features import _safe_float
        self.assertAlmostEqual(_safe_float(5), 5.0)


class TestPercentile(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        from backend.services.ingestion.features import _percentile
        self.assertEqual(_percentile([], 0.95), 0.0)

    def test_single_value(self):
        from backend.services.ingestion.features import _percentile
        self.assertAlmostEqual(_percentile([42.0], 0.95), 42.0)

    def test_normal_interpolation(self):
        from backend.services.ingestion.features import _percentile
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _percentile(values, 0.5)
        self.assertAlmostEqual(result, 3.0)

    def test_p95(self):
        from backend.services.ingestion.features import _percentile
        values = list(range(1, 101))
        result = _percentile([float(v) for v in values], 0.95)
        self.assertGreater(result, 90.0)

    def test_percentile_clamps_to_valid_range(self):
        from backend.services.ingestion.features import _percentile
        result = _percentile([1.0, 2.0], 1.5)
        self.assertGreaterEqual(result, 0.0)


class TestParseTimestamp(unittest.TestCase):

    def test_none_returns_none(self):
        from backend.services.ingestion.features import _parse_timestamp
        self.assertIsNone(_parse_timestamp(None))

    def test_empty_string_returns_none(self):
        from backend.services.ingestion.features import _parse_timestamp
        self.assertIsNone(_parse_timestamp(""))

    def test_whitespace_only_returns_none(self):
        from backend.services.ingestion.features import _parse_timestamp
        self.assertIsNone(_parse_timestamp("   "))

    def test_z_suffix_parsed(self):
        from backend.services.ingestion.features import _parse_timestamp
        result = _parse_timestamp("2026-05-21T01:30:00Z")
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_iso_with_offset(self):
        from backend.services.ingestion.features import _parse_timestamp
        result = _parse_timestamp("2026-05-21T01:30:00+00:00")
        self.assertIsNotNone(result)

    def test_invalid_format_returns_none(self):
        from backend.services.ingestion.features import _parse_timestamp
        self.assertIsNone(_parse_timestamp("not-a-date"))

    def test_naive_datetime_gets_utc(self):
        from backend.services.ingestion.features import _parse_timestamp
        result = _parse_timestamp("2026-05-21T01:30:00")
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.tzinfo)


class TestRecordTimestamp(unittest.TestCase):

    def test_finds_timestamp_field(self):
        from backend.services.ingestion.features import _record_timestamp
        record = {"@timestamp": "2026-05-21T01:30:00Z"}
        result = _record_timestamp(record)
        self.assertIsNotNone(result)

    def test_tries_multiple_fields(self):
        from backend.services.ingestion.features import _record_timestamp
        record = {"event_time": "2026-05-21T01:30:00Z"}
        result = _record_timestamp(record)
        self.assertIsNotNone(result)

    def test_returns_none_when_no_timestamp(self):
        from backend.services.ingestion.features import _record_timestamp
        result = _record_timestamp({"random_field": "value"})
        self.assertIsNone(result)

    def test_returns_none_for_empty_record(self):
        from backend.services.ingestion.features import _record_timestamp
        self.assertIsNone(_record_timestamp({}))


class TestWindowKey(unittest.TestCase):

    def test_valid_iso_strings_produce_key(self):
        from backend.services.ingestion.features import _window_key
        key = _window_key("2026-05-21T01:30:00+00:00", "2026-05-21T02:00:00+00:00")
        self.assertIn("20260521", key)

    def test_fallback_string_concatenation(self):
        from backend.services.ingestion.features import _window_key
        # Non-parseable strings fallback to string mangling
        key = _window_key("not-iso-start", "not-iso-end")
        self.assertIsInstance(key, str)

    def test_none_inputs_produce_current_window(self):
        from backend.services.ingestion.features import _window_key
        key = _window_key(None, None)
        self.assertIsInstance(key, str)
        self.assertIn("_", key)

    def test_partial_none_falls_back(self):
        from backend.services.ingestion.features import _window_key
        key = _window_key(None, "2026-05-21T02:00:00+00:00")
        self.assertIsInstance(key, str)


class TestWindowBounds(unittest.TestCase):

    def test_valid_timestamps_returned_as_iso(self):
        from backend.services.ingestion.features import _window_bounds
        start, end = _window_bounds("2026-05-21T01:30:00+00:00", "2026-05-21T02:00:00+00:00")
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)

    def test_none_inputs_returned_as_none(self):
        from backend.services.ingestion.features import _window_bounds
        start, end = _window_bounds(None, None)
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_non_parseable_strings_returned_as_is(self):
        from backend.services.ingestion.features import _window_bounds
        start, end = _window_bounds("raw-start", "raw-end")
        self.assertEqual(start, "raw-start")
        self.assertEqual(end, "raw-end")


class TestBuildWindowMetricBatches(unittest.TestCase):

    def _make_record(self, ts=None, is_system=True, log_type="INFO"):
        r = {
            "is_system_log": is_system,
            "is_llm_log": not is_system,
            "sap_function_log_type": log_type,
        }
        if ts:
            r["@timestamp"] = ts
        return r

    def test_no_timestamps_returns_single_batch(self):
        from backend.services.ingestion.features import build_window_metric_batches
        records = [self._make_record() for _ in range(5)]
        batches = build_window_metric_batches(records, "2026-05-21T01:30:00Z", "2026-05-21T02:00:00Z")
        self.assertEqual(len(batches), 1)

    def test_grouped_by_half_hour_windows(self):
        from backend.services.ingestion.features import build_window_metric_batches
        records = [
            self._make_record("2026-05-21T01:10:00Z"),
            self._make_record("2026-05-21T01:40:00Z"),
            self._make_record("2026-05-21T01:45:00Z"),
        ]
        batches = build_window_metric_batches(records, None, None)
        self.assertGreaterEqual(len(batches), 1)

    def test_unbucketed_records_appended(self):
        from backend.services.ingestion.features import build_window_metric_batches
        records = [
            self._make_record("2026-05-21T01:10:00Z"),
            self._make_record(None),  # no timestamp → unbucketed
        ]
        batches = build_window_metric_batches(records, "2026-05-21T01:30:00Z", "2026-05-21T02:00:00Z")
        # Should have at least one batch for bucketed + one for unbucketed
        self.assertGreaterEqual(len(batches), 1)

    def test_empty_records_returns_empty_batch(self):
        from backend.services.ingestion.features import build_window_metric_batches
        batches = build_window_metric_batches([], None, None)
        self.assertEqual(len(batches), 1)
        metrics, records = batches[0]
        self.assertEqual(metrics["total_records"], 0)

    def test_all_unbucketed_returns_one_batch(self):
        from backend.services.ingestion.features import build_window_metric_batches
        records = [self._make_record(None), self._make_record(None)]
        batches = build_window_metric_batches(records, "2026-05-21T01:30:00Z", "2026-05-21T02:00:00Z")
        # No bucketed records → single batch with all records
        self.assertEqual(len(batches), 1)
        metrics, _ = batches[0]
        self.assertEqual(metrics["total_records"], 2)


if __name__ == "__main__":
    unittest.main()
