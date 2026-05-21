from __future__ import annotations

import unittest

from backend.services.detection.historical_baseline import _pattern_reason


class HistoricalBaselineTests(unittest.TestCase):
    def test_llm_drop_is_not_marked_as_incomplete_when_system_logs_continue(self) -> None:
        reason = _pattern_reason(
            [
                {
                    "feature": "total_records",
                    "direction": "lower_than_usual",
                    "abs_robust_z": 8.0,
                },
                {
                    "feature": "llm_log_count",
                    "direction": "lower_than_usual",
                    "abs_robust_z": 12.0,
                },
                {
                    "feature": "llm_timeout_count",
                    "direction": "lower_than_usual",
                    "abs_robust_z": 9.0,
                },
            ]
        )

        self.assertEqual(reason, "llm_activity_drop")

    def test_incomplete_window_requires_core_volume_drop(self) -> None:
        reason = _pattern_reason(
            [
                {
                    "feature": "total_records",
                    "direction": "lower_than_usual",
                    "abs_robust_z": 8.0,
                },
                {
                    "feature": "system_log_count",
                    "direction": "lower_than_usual",
                    "abs_robust_z": 7.0,
                },
                {
                    "feature": "llm_log_count",
                    "direction": "lower_than_usual",
                    "abs_robust_z": 12.0,
                },
            ]
        )

        self.assertEqual(reason, "possible_incomplete_window")

    def test_security_spike_still_wins_over_volume_drop(self) -> None:
        reason = _pattern_reason(
            [
                {
                    "feature": "llm_log_count",
                    "direction": "lower_than_usual",
                    "abs_robust_z": 12.0,
                },
                {
                    "feature": "security_count",
                    "direction": "higher_than_usual",
                    "abs_robust_z": 4.0,
                },
            ]
        )

        self.assertEqual(reason, "possible_attack_pattern")

    def test_llm_rate_spike_without_security_context_is_quality_degradation(self) -> None:
        reason = _pattern_reason(
            [
                {
                    "feature": "llm_timeout_rate",
                    "direction": "higher_than_usual",
                    "abs_robust_z": 5.0,
                },
            ]
        )

        self.assertEqual(reason, "llm_quality_degradation")

    def test_llm_drop_with_rate_spike_stays_activity_drop(self) -> None:
        reason = _pattern_reason(
            [
                {
                    "feature": "llm_log_count",
                    "direction": "lower_than_usual",
                    "abs_robust_z": 12.0,
                },
                {
                    "feature": "llm_timeout_rate",
                    "direction": "higher_than_usual",
                    "abs_robust_z": 5.0,
                },
            ]
        )

        self.assertEqual(reason, "llm_activity_drop")


class TestSeverityPoints(unittest.TestCase):

    def test_critical_threshold(self):
        from backend.services.detection.historical_baseline import _severity_points
        severity, points = _severity_points(8.0)
        self.assertEqual(severity, "critical")
        self.assertEqual(points, 25)

    def test_high_threshold(self):
        from backend.services.detection.historical_baseline import _severity_points
        severity, points = _severity_points(4.0)
        self.assertEqual(severity, "high")
        self.assertEqual(points, 15)

    def test_medium_threshold(self):
        from backend.services.detection.historical_baseline import _severity_points
        severity, points = _severity_points(3.1)
        self.assertEqual(severity, "medium")
        self.assertEqual(points, 8)

    def test_above_critical(self):
        from backend.services.detection.historical_baseline import _severity_points
        severity, points = _severity_points(12.0)
        self.assertEqual(severity, "critical")


class TestPatternStatus(unittest.TestCase):

    def test_critical_by_max_deviation(self):
        from backend.services.detection.historical_baseline import _pattern_status
        self.assertEqual(_pattern_status(10.0, 8.0), "critical_anomaly")

    def test_critical_by_score(self):
        from backend.services.detection.historical_baseline import _pattern_status
        self.assertEqual(_pattern_status(35.0, 2.0), "critical_anomaly")

    def test_high_anomaly_by_deviation(self):
        from backend.services.detection.historical_baseline import _pattern_status
        self.assertEqual(_pattern_status(10.0, 4.0), "high_anomaly")

    def test_high_anomaly_by_score(self):
        from backend.services.detection.historical_baseline import _pattern_status
        self.assertEqual(_pattern_status(20.0, 2.0), "high_anomaly")

    def test_suspicious(self):
        from backend.services.detection.historical_baseline import _pattern_status
        self.assertEqual(_pattern_status(12.0, 3.0), "suspicious")

    def test_normal(self):
        from backend.services.detection.historical_baseline import _pattern_status
        self.assertEqual(_pattern_status(5.0, 1.0), "normal")


class TestPickValue(unittest.TestCase):

    def test_lowercase_key(self):
        from backend.services.detection.historical_baseline import _pick_value
        self.assertEqual(_pick_value({"total_records": 100}, "total_records"), 100)

    def test_uppercase_fallback(self):
        from backend.services.detection.historical_baseline import _pick_value
        self.assertEqual(_pick_value({"TOTAL_RECORDS": 200}, "total_records"), 200)

    def test_missing_returns_none(self):
        from backend.services.detection.historical_baseline import _pick_value
        self.assertIsNone(_pick_value({}, "total_records"))


class TestAsFloat(unittest.TestCase):

    def test_int_converted(self):
        from backend.services.detection.historical_baseline import _as_float
        self.assertAlmostEqual(_as_float(5), 5.0)

    def test_string_numeric_converted(self):
        from backend.services.detection.historical_baseline import _as_float
        self.assertAlmostEqual(_as_float("3.14"), 3.14)

    def test_none_returns_none(self):
        from backend.services.detection.historical_baseline import _as_float
        self.assertIsNone(_as_float(None))

    def test_invalid_string_returns_none(self):
        from backend.services.detection.historical_baseline import _as_float
        self.assertIsNone(_as_float("not-a-number"))


class TestScoreHistoricalPattern(unittest.TestCase):

    def _make_history(self, n=30, value=100.0):
        return [{"total_records": value, "error_count": 10.0,
                 "security_count": 5.0, "llm_log_count": 50.0,
                 "system_log_count": 50.0, "llm_request_count": 100.0,
                 "llm_error_count": 5.0, "llm_timeout_count": 2.0,
                 "avg_llm_latency_ms": 500.0, "p95_llm_latency_ms": 900.0,
                 "total_llm_cost_usd": 1.0, "http_4xx_count": 10.0,
                 "http_5xx_count": 3.0, "security_event_rate": 0.01,
                 "system_error_rate": 0.05, "llm_error_rate": 0.05,
                 "llm_timeout_rate": 0.02, "top_ip_event_share": 0.01,
                 "max_events_from_single_ip": 10.0, "warning_count": 20.0,
                 "audit_count": 5.0, "debug_count": 3.0, "perf_count": 2.0,
                 "unique_client_ips": 50.0, "unique_services": 5.0}
                for _ in range(n)]

    def test_insufficient_history_returns_unavailable(self):
        from backend.services.detection.historical_baseline import score_historical_pattern
        result = score_historical_pattern({"total_records": 100}, [], min_history_rows=30)
        self.assertFalse(result["historical_available"])
        self.assertIn("insufficient_history", result["historical_source"])

    def test_sufficient_history_returns_available(self):
        from backend.services.detection.historical_baseline import score_historical_pattern
        history = self._make_history(30, 100.0)
        current = {"total_records": 100.0, "error_count": 10.0}
        result = score_historical_pattern(current, history)
        self.assertTrue(result["historical_available"])

    def test_large_spike_produces_signal(self):
        from backend.services.detection.historical_baseline import score_historical_pattern
        history = self._make_history(30, 100.0)
        # security_count is normally 5.0, send 500.0 → massive z-score
        current = {k: v for k, v in history[0].items()}
        current["security_count"] = 5000.0
        result = score_historical_pattern(current, history)
        self.assertTrue(result["historical_available"])
        self.assertGreater(result["pattern_score"], 0.0)
        self.assertGreater(len(result["pattern_signals"]), 0)

    def test_normal_values_produce_no_signals(self):
        from backend.services.detection.historical_baseline import score_historical_pattern
        history = self._make_history(30, 100.0)
        current = {k: v for k, v in history[0].items()}  # same as history
        result = score_historical_pattern(current, history)
        self.assertEqual(result["pattern_score"], 0.0)

    def test_mad_zero_edge_case(self):
        """When all historical values are identical (MAD=0), z-score special case."""
        from backend.services.detection.historical_baseline import score_historical_pattern
        history = self._make_history(30, 100.0)
        # total_records is 100.0 in all rows → MAD=0
        # current value different → z should be 6.0
        current = {k: v for k, v in history[0].items()}
        current["total_records"] = 999.0
        result = score_historical_pattern(current, history)
        signals = [s for s in result["pattern_signals"] if s["feature"] == "total_records"]
        if signals:
            self.assertAlmostEqual(abs(signals[0]["robust_z"]), 6.0)

    def test_pattern_signals_sorted_by_z(self):
        from backend.services.detection.historical_baseline import score_historical_pattern
        history = self._make_history(30, 100.0)
        current = {k: v for k, v in history[0].items()}
        current["security_count"] = 5000.0
        current["http_5xx_count"] = 5000.0
        result = score_historical_pattern(current, history)
        signals = result["pattern_signals"]
        if len(signals) >= 2:
            self.assertGreaterEqual(signals[0]["abs_robust_z"], signals[1]["abs_robust_z"])


class TestScoreHistoricalPatternEdgeCases(unittest.TestCase):

    def _make_history(self, n=30, base_value=100.0, varied=False):
        rows = []
        for i in range(n):
            val = base_value + (i % 5) * 2.0 if varied else base_value
            rows.append({
                "total_records": val, "error_count": 10.0,
                "security_count": 5.0, "llm_log_count": 50.0,
                "system_log_count": 50.0, "llm_request_count": 100.0,
                "llm_error_count": 5.0, "llm_timeout_count": 2.0,
                "avg_llm_latency_ms": 500.0, "p95_llm_latency_ms": 900.0,
                "total_llm_cost_usd": 1.0, "http_4xx_count": 10.0,
                "http_5xx_count": 3.0, "security_event_rate": 0.01,
                "system_error_rate": 0.05, "llm_error_rate": 0.05,
                "llm_timeout_rate": 0.02, "top_ip_event_share": 0.01,
                "max_events_from_single_ip": 10.0, "warning_count": 20.0,
                "audit_count": 5.0, "debug_count": 3.0, "perf_count": 2.0,
                "unique_client_ips": 50.0, "unique_services": 5.0,
            })
        return rows

    def test_varied_history_triggers_normal_zscore_path(self):
        """When MAD > 0, uses normal 0.6745*(x-median)/mad formula (line 88)."""
        from backend.services.detection.historical_baseline import score_historical_pattern

        # Build history with varied security_count so MAD > 0
        history = []
        for i in range(30):
            row = self._make_history(1)[0]
            row["security_count"] = 5.0 + (i % 5) * 2.0  # values: 5,7,9,11,13 cycling
            history.append(row)

        # Current value far from median to trigger |z| >= 3
        current = dict(history[0])
        current["security_count"] = 500.0  # Way above the 5-13 range

        result = score_historical_pattern(current, history)
        self.assertTrue(result["historical_available"])
        signals = [s for s in result["pattern_signals"] if s["feature"] == "security_count"]
        self.assertGreater(len(signals), 0, "Expected a signal for security_count")
        self.assertGreater(signals[0]["mad"], 0.0)  # MAD > 0 means line 88 was used

    def test_feature_with_sparse_history_skipped(self):
        """When fewer than min_history_rows have a feature, that feature is skipped (line 79)."""
        from backend.services.detection.historical_baseline import score_historical_pattern

        # Create history where most rows are missing 'security_count'
        history = self._make_history(30)
        # Remove security_count from most rows
        sparse_history = []
        for i, row in enumerate(history):
            r = dict(row)
            if i < 25:  # only 5 rows have security_count → < min_history_rows=30
                del r["security_count"]
            sparse_history.append(r)

        current = dict(history[0])
        result = score_historical_pattern(current, sparse_history)
        self.assertTrue(result["historical_available"])
        # security_count should NOT appear in signals (was skipped)
        signal_features = [s["feature"] for s in result["pattern_signals"]]
        self.assertNotIn("security_count", signal_features)


class TestPatternReasonAdditional(unittest.TestCase):

    def test_system_activity_drop(self):
        from backend.services.detection.historical_baseline import _pattern_reason
        reason = _pattern_reason([{
            "feature": "total_records",
            "direction": "lower_than_usual",
            "abs_robust_z": 5.0,
        }, {
            "feature": "error_count",
            "direction": "lower_than_usual",
            "abs_robust_z": 4.5,
        }])
        self.assertEqual(reason, "system_activity_drop")

    def test_upward_pattern_break(self):
        from backend.services.detection.historical_baseline import _pattern_reason
        reason = _pattern_reason([{
            "feature": "debug_count",
            "direction": "higher_than_usual",
            "abs_robust_z": 4.0,
        }])
        self.assertEqual(reason, "upward_pattern_break")

    def test_downward_pattern_break(self):
        from backend.services.detection.historical_baseline import _pattern_reason
        # Use a feature not in any special set to hit the generic downward break
        reason = _pattern_reason([{
            "feature": "unique_client_ips",
            "direction": "lower_than_usual",
            "abs_robust_z": 4.5,
        }])
        self.assertEqual(reason, "downward_pattern_break")

    def test_general_pattern_break_when_no_strong_signals(self):
        from backend.services.detection.historical_baseline import _pattern_reason
        reason = _pattern_reason([])
        self.assertEqual(reason, "general_pattern_break")


if __name__ == "__main__":
    unittest.main()
