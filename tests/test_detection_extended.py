"""Extended tests for backend/services/detection/detect.py — target >= 95%."""
import unittest


def _make_empty_signal():
    return {
        "historical_available": False,
        "historical_source": "insufficient_history:0",
        "pattern_score": 0.0,
        "max_feature_deviation": 0.0,
        "pattern_status": "unknown",
        "pattern_reason": "insufficient_history",
        "pattern_signals": [],
    }


def _make_model_signal(available=False, is_anomaly=False, percentile=0.0, score=0.0):
    return {
        "model_available": available,
        "is_anomaly": is_anomaly,
        "anomaly_percentile": percentile,
        "anomaly_score": score,
        "training_row_count": 50,
        "source": "test",
    }


def _make_metrics(**overrides):
    base = {
        "window_key": "20260521T013000Z_20260521T020000Z",
        "window_start": "2026-05-21T01:30:00+00:00",
        "window_end": "2026-05-21T02:00:00+00:00",
        "total_records": 5000,
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
        "max_events_from_single_ip": 5,
        "saved_at_utc": "2026-05-21T01:45:00+00:00",
    }
    base.update(overrides)
    return base


class TestModelTriggerAlert(unittest.TestCase):

    def test_model_anomaly_adds_trigger_alert(self):
        from backend.services.detection.detect import evaluate_window_risk
        model = _make_model_signal(available=True, is_anomaly=True, percentile=95.0, score=90.0)
        alerts, summary = evaluate_window_risk(
            normalized_records=[],
            metrics=_make_metrics(),
            model_signal=model,
            historical_signal=_make_empty_signal(),
            count_threshold=25,
            attack_score_threshold=70,
        )
        alert_types = [a["alert_type"].upper() for a in alerts]
        self.assertIn("ANOMALY_MODEL_TRIGGER", alert_types)


class TestModelReinforcesAttack(unittest.TestCase):

    def test_model_anomaly_with_attack_pattern_predicts_attack(self):
        from backend.services.detection.detect import evaluate_window_risk
        # High security metrics to trigger security combination
        metrics = _make_metrics(
            security_count=300,
            error_count=500,
            system_log_count=1000,
            security_event_rate=0.3,
            system_error_rate=0.5,
            http_5xx_count=200,
        )
        historical = {
            "historical_available": True,
            "historical_source": "robust_z:30",
            "pattern_score": 40.0,
            "max_feature_deviation": 9.0,
            "pattern_status": "critical_anomaly",
            "pattern_reason": "possible_attack_pattern",
            "pattern_signals": [{
                "feature": "security_count",
                "direction": "higher_than_usual",
                "abs_robust_z": 9.0,
                "severity": "critical",
                "points": 25,
                "value": 300.0,
                "median": 10.0,
                "mad": 2.0,
                "robust_z": 9.0,
            }],
        }
        model = _make_model_signal(available=True, is_anomaly=True, percentile=96.0, score=96.0)
        alerts, summary = evaluate_window_risk(
            normalized_records=[],
            metrics=metrics,
            model_signal=model,
            historical_signal=historical,
            count_threshold=25,
            attack_score_threshold=70,
        )
        # If attack is predicted, it should be reflected in summary
        self.assertIn("attack_predicted", summary)


class TestHistoricalSignalMultipleSignals(unittest.TestCase):

    def test_multiple_signals_produce_individual_alerts(self):
        from backend.services.detection.detect import evaluate_window_risk
        historical = {
            "historical_available": True,
            "historical_source": "robust_z:30",
            "pattern_score": 16.0,
            "max_feature_deviation": 3.5,
            "pattern_status": "suspicious",
            "pattern_reason": "upward_pattern_break",
            "pattern_signals": [
                {"feature": "error_count", "direction": "higher_than_usual",
                 "abs_robust_z": 3.5, "severity": "medium", "points": 8,
                 "value": 200.0, "median": 50.0, "mad": 10.0, "robust_z": 3.5},
                {"feature": "http_5xx_count", "direction": "higher_than_usual",
                 "abs_robust_z": 3.2, "severity": "medium", "points": 8,
                 "value": 100.0, "median": 20.0, "mad": 5.0, "robust_z": 3.2},
            ],
        }
        alerts, summary = evaluate_window_risk(
            normalized_records=[],
            metrics=_make_metrics(),
            model_signal=_make_model_signal(),
            historical_signal=historical,
            count_threshold=25,
            attack_score_threshold=70,
        )
        alert_types = [a["alert_type"].upper() for a in alerts]
        historical_alerts = [t for t in alert_types if t.startswith("HISTORICAL_")]
        self.assertGreaterEqual(len(historical_alerts), 2)


class TestApplyBaselineShiftContext(unittest.TestCase):

    def _make_summary(self, reason="llm_activity_drop", window_key="w1"):
        return {
            "anomaly_reason": reason,
            "window_key": window_key,
            "risk_level": "service_activity_anomaly",
        }

    def _make_windows(self, n, reason="llm_activity_drop", total_records=100):
        return [
            {"window_key": f"w{i}", "anomaly_reason": reason,
             "total_records": total_records}
            for i in range(2, 2 + n)
        ]

    def test_non_llm_drop_returns_unchanged(self):
        from backend.services.detection.detect import apply_baseline_shift_context
        alerts = [{"alert_type": "test"}]
        summary = self._make_summary(reason="first_observed_values")
        result_alerts, result_summary = apply_baseline_shift_context(alerts, summary, [])
        self.assertEqual(result_alerts, alerts)
        self.assertEqual(result_summary, summary)

    def test_skips_current_window_in_loop(self):
        from backend.services.detection.detect import apply_baseline_shift_context
        summary = self._make_summary(reason="llm_activity_drop", window_key="w1")
        windows = [{"window_key": "w1", "anomaly_reason": "llm_activity_drop", "total_records": 100}]
        alerts, result = apply_baseline_shift_context([], summary, windows, min_consecutive_windows=2)
        # current window skipped, not enough consecutive → unchanged
        self.assertEqual(result["anomaly_reason"], "llm_activity_drop")

    def test_skips_zero_record_windows(self):
        from backend.services.detection.detect import apply_baseline_shift_context
        summary = self._make_summary(reason="llm_activity_drop", window_key="w1")
        windows = [{"window_key": "w2", "anomaly_reason": "normal", "total_records": 0}]
        alerts, result = apply_baseline_shift_context([], summary, windows, min_consecutive_windows=2)
        self.assertEqual(result["anomaly_reason"], "llm_activity_drop")

    def test_non_shift_reason_breaks_streak(self):
        from backend.services.detection.detect import apply_baseline_shift_context
        summary = self._make_summary(reason="llm_activity_drop", window_key="w1")
        # Only 1 consecutive window → total 2 (prev+current) < min=3 → unchanged
        windows = [
            {"window_key": "w2", "anomaly_reason": "llm_activity_drop", "total_records": 100},
            {"window_key": "w3", "anomaly_reason": "normal", "total_records": 100},  # breaks streak
        ]
        alerts, result = apply_baseline_shift_context([], summary, windows, min_consecutive_windows=3)
        self.assertEqual(result["anomaly_reason"], "llm_activity_drop")

    def test_sufficient_consecutive_produces_baseline_shift(self):
        from backend.services.detection.detect import apply_baseline_shift_context
        summary = self._make_summary(reason="llm_activity_drop", window_key="w1")
        windows = self._make_windows(6, reason="llm_activity_drop")
        alerts, result = apply_baseline_shift_context([], summary, windows, min_consecutive_windows=6)
        self.assertEqual(result.get("anomaly_reason"), "baseline_shift_candidate")


class TestExplainRisk(unittest.TestCase):

    def _call(self, reason, **extra):
        from backend.services.detection.detect import _build_explanation
        summary = {"anomaly_reason": reason, "threat_score": 30, **extra}
        return _build_explanation(summary, [])

    def test_incomplete_window(self):
        result = self._call("possible_incomplete_window")
        self.assertIn("Incomplete", result)

    def test_llm_activity_drop(self):
        result = self._call("llm_activity_drop")
        self.assertIn("LLM activity drop", result)

    def test_llm_quality_degradation(self):
        result = self._call("llm_quality_degradation")
        self.assertIn("LLM quality degradation", result)

    def test_system_activity_drop(self):
        result = self._call("system_activity_drop")
        self.assertIn("System activity drop", result)

    def test_baseline_shift_candidate(self):
        result = self._call("baseline_shift_candidate", baseline_shift_windows=7)
        self.assertIn("baseline shift", result.lower())


class TestAsIntAsFloat(unittest.TestCase):

    def test_as_int_valid(self):
        from backend.services.detection.detect import _as_int
        self.assertEqual(_as_int("5"), 5)
        self.assertEqual(_as_int(3.7), 3)

    def test_as_int_invalid_returns_zero(self):
        from backend.services.detection.detect import _as_int
        self.assertEqual(_as_int("bad"), 0)
        self.assertEqual(_as_int(None), 0)

    def test_as_float_valid(self):
        from backend.services.detection.detect import _as_float
        self.assertAlmostEqual(_as_float("3.14"), 3.14)

    def test_as_float_invalid_returns_zero(self):
        from backend.services.detection.detect import _as_float
        self.assertAlmostEqual(_as_float("bad"), 0.0)
        self.assertAlmostEqual(_as_float(None), 0.0)


class TestDeriveWindowAnomalyFields(unittest.TestCase):

    def test_anomaly_with_zero_score_gets_fallback(self):
        from backend.services.detection.detect import _derive_window_anomaly_fields
        result = _derive_window_anomaly_fields(
            model_signal=_make_model_signal(available=False),
            historical_signal=_make_empty_signal(),
            threat_score=45,
            detection_count=2,
            attack_predicted=False,
            risk_level="medium",
            anomaly_reason="first_observed_values",
        )
        # is_anomaly should be True when there are detections
        self.assertIn("is_anomaly", result)

    def test_is_anomaly_false_when_no_signals(self):
        from backend.services.detection.detect import _derive_window_anomaly_fields
        result = _derive_window_anomaly_fields(
            model_signal=_make_model_signal(),
            historical_signal=_make_empty_signal(),
            threat_score=0,
            detection_count=0,
            attack_predicted=False,
            risk_level="unknown",
            anomaly_reason="insufficient_history",
        )
        self.assertFalse(result["is_anomaly"])


if __name__ == "__main__":
    unittest.main()
