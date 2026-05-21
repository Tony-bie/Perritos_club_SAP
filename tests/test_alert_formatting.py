"""Tests for backend/services/detection/alert.py — target >= 70%."""
import unittest


def _make_metrics(**overrides):
    base = {
        "window_key": "20260521T013000Z_20260521T020000Z",
        "window_start": "2026-05-21T01:30:00+00:00",
        "window_end": "2026-05-21T02:00:00+00:00",
        "risk_level": "medium",
        "threat_score": 45,
        "attack_predicted": False,
        "is_anomaly": True,
        "anomaly_percentile": 82.5,
        "detection_count": 3,
        "anomaly_reason": "first_observed_values",
    }
    base.update(overrides)
    return base


def _make_alert(**overrides):
    base = {
        "alert_type": "security_spike",
        "severity": "high",
        "score": 85,
        "payload": {"feature": "security_count", "abs_robust_z": 4.5},
    }
    base.update(overrides)
    return base


class TestFormatAlertEvents(unittest.TestCase):

    def test_wraps_each_alert_in_event_format(self):
        from backend.services.detection.alert import format_alert_events
        alerts = [_make_alert(), _make_alert(alert_type="http_spike")]
        events = format_alert_events(alerts, run_id="run-123")
        self.assertEqual(len(events), 2)

    def test_event_has_required_fields(self):
        from backend.services.detection.alert import format_alert_events
        events = format_alert_events([_make_alert()], run_id="run-abc")
        e = events[0]
        self.assertIn("alert_id", e)
        self.assertIn("run_id", e)
        self.assertIn("detected_at_utc", e)
        self.assertIn("alert_type", e)
        self.assertIn("severity", e)
        self.assertIn("payload", e)

    def test_run_id_is_set_correctly(self):
        from backend.services.detection.alert import format_alert_events
        events = format_alert_events([_make_alert()], run_id="run-xyz")
        self.assertEqual(events[0]["run_id"], "run-xyz")

    def test_alert_type_propagated(self):
        from backend.services.detection.alert import format_alert_events
        events = format_alert_events([_make_alert(alert_type="novel_ip")], run_id="r")
        self.assertEqual(events[0]["alert_type"], "novel_ip")

    def test_empty_alerts_returns_empty_list(self):
        from backend.services.detection.alert import format_alert_events
        self.assertEqual(format_alert_events([], run_id="r"), [])

    def test_each_event_has_unique_alert_id(self):
        from backend.services.detection.alert import format_alert_events
        events = format_alert_events([_make_alert(), _make_alert()], run_id="r")
        ids = {e["alert_id"] for e in events}
        self.assertEqual(len(ids), 2)

    def test_missing_alert_type_defaults_to_unknown(self):
        from backend.services.detection.alert import format_alert_events
        events = format_alert_events([{"severity": "low"}], run_id="r")
        self.assertEqual(events[0]["alert_type"], "UNKNOWN")


class TestBuildAlertSubmissionMessage(unittest.TestCase):

    def test_returns_string(self):
        from backend.services.detection.alert import build_alert_submission_message
        msg = build_alert_submission_message(_make_metrics(), [_make_alert()])
        self.assertIsInstance(msg, str)

    def test_contains_what_when_why(self):
        from backend.services.detection.alert import build_alert_submission_message
        msg = build_alert_submission_message(_make_metrics(), [_make_alert()])
        self.assertIn("WHAT:", msg)
        self.assertIn("WHEN:", msg)
        self.assertIn("WHY:", msg)

    def test_attack_predicted_changes_what(self):
        from backend.services.detection.alert import build_alert_submission_message
        metrics = _make_metrics(attack_predicted=True)
        msg = build_alert_submission_message(metrics, [_make_alert()])
        self.assertIn("attack", msg.lower())

    def test_anomaly_detected_changes_what(self):
        from backend.services.detection.alert import build_alert_submission_message
        metrics = _make_metrics(attack_predicted=False)
        msg = build_alert_submission_message(metrics, [_make_alert()])
        self.assertIn("anomaly", msg.lower())

    def test_message_max_length_respected(self):
        from backend.services.detection.alert import build_alert_submission_message, ALERT_MESSAGE_MAX_LENGTH
        # Long window key and many alerts should still be truncated
        metrics = _make_metrics(window_key="x" * 500)
        msg = build_alert_submission_message(metrics, [_make_alert()])
        self.assertLessEqual(len(msg), ALERT_MESSAGE_MAX_LENGTH)

    def test_notification_reason_included_in_why(self):
        from backend.services.detection.alert import build_alert_submission_message
        msg = build_alert_submission_message(_make_metrics(), [_make_alert()], "attack_predicted")
        self.assertIn("attack_predicted", msg)

    def test_empty_alerts_no_crash(self):
        from backend.services.detection.alert import build_alert_submission_message
        msg = build_alert_submission_message(_make_metrics(), [])
        self.assertIn("WHAT:", msg)

    def test_model_anomaly_percentile_in_why(self):
        from backend.services.detection.alert import build_alert_submission_message
        metrics = _make_metrics(is_anomaly=True, anomaly_percentile=95.0)
        msg = build_alert_submission_message(metrics, [_make_alert()])
        self.assertIn("95.0", msg)


class TestCoerceWhen(unittest.TestCase):

    def test_uses_window_end_first(self):
        from backend.services.detection.alert import _coerce_when
        result = _coerce_when({"window_end": "2026-05-21T02:00:00"})
        self.assertEqual(result, "2026-05-21T02:00:00")

    def test_falls_back_to_saved_at_utc(self):
        from backend.services.detection.alert import _coerce_when
        result = _coerce_when({"saved_at_utc": "2026-05-21T01:45:00"})
        self.assertEqual(result, "2026-05-21T01:45:00")

    def test_falls_back_to_window_start(self):
        from backend.services.detection.alert import _coerce_when
        result = _coerce_when({"window_start": "2026-05-21T01:30:00"})
        self.assertEqual(result, "2026-05-21T01:30:00")

    def test_falls_back_to_now_when_all_missing(self):
        from backend.services.detection.alert import _coerce_when
        result = _coerce_when({})
        self.assertIsInstance(result, str)
        self.assertIn("2026", result)


class TestBuildWhy(unittest.TestCase):

    def test_includes_detection_count_and_score(self):
        from backend.services.detection.alert import _build_why
        result = _build_why(_make_metrics(), [])
        self.assertIn("detection_count=3", result)
        self.assertIn("threat_score=45", result)

    def test_includes_top_signal_info(self):
        from backend.services.detection.alert import _build_why
        result = _build_why(_make_metrics(), [_make_alert()])
        self.assertIn("top_signal=SECURITY_SPIKE", result)

    def test_includes_feature_when_present(self):
        from backend.services.detection.alert import _build_why
        result = _build_why(_make_metrics(), [_make_alert()])
        self.assertIn("feature=security_count", result)

    def test_includes_robust_z_when_present(self):
        from backend.services.detection.alert import _build_why
        result = _build_why(_make_metrics(), [_make_alert()])
        self.assertIn("robust_z=4.50", result)

    def test_no_crash_when_robust_z_not_numeric(self):
        from backend.services.detection.alert import _build_why
        alert = _make_alert(payload={"abs_robust_z": "not-a-number"})
        result = _build_why(_make_metrics(), [alert])
        self.assertIn("detection_count", result)

    def test_model_anomaly_included_when_is_anomaly(self):
        from backend.services.detection.alert import _build_why
        metrics = _make_metrics(is_anomaly=True, anomaly_percentile=87.3)
        result = _build_why(metrics, [])
        self.assertIn("model_anomaly_percentile=87.3", result)

    def test_notification_reason_prepended(self):
        from backend.services.detection.alert import _build_why
        result = _build_why(_make_metrics(), [], "threat_score_gte_threshold")
        self.assertTrue(result.startswith("trigger=threat_score_gte_threshold"))


class TestShouldSubmitAlertNotification(unittest.TestCase):

    def test_no_alerts_returns_false(self):
        from backend.services.detection.alert import should_submit_alert_notification
        ok, reason = should_submit_alert_notification(_make_metrics(), [], 70)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_detection_signals")

    def test_incomplete_window_suppressed(self):
        from backend.services.detection.alert import should_submit_alert_notification
        metrics = _make_metrics(anomaly_reason="possible_incomplete_window")
        ok, reason = should_submit_alert_notification(metrics, [_make_alert()], 70)
        self.assertFalse(ok)
        self.assertIn("suppressed", reason)

    def test_attack_predicted_returns_true(self):
        from backend.services.detection.alert import should_submit_alert_notification
        metrics = _make_metrics(attack_predicted=True)
        ok, reason = should_submit_alert_notification(metrics, [_make_alert()], 70)
        self.assertTrue(ok)
        self.assertEqual(reason, "attack_predicted")

    def test_threat_score_above_threshold_returns_true(self):
        from backend.services.detection.alert import should_submit_alert_notification
        metrics = _make_metrics(threat_score=80, attack_predicted=False)
        ok, reason = should_submit_alert_notification(metrics, [_make_alert()], 70)
        self.assertTrue(ok)
        self.assertIn("threat_score_gte_threshold", reason)

    def test_extreme_percentile_with_enough_detections_returns_true(self):
        from backend.services.detection.alert import should_submit_alert_notification
        metrics = _make_metrics(
            threat_score=30, attack_predicted=False,
            is_anomaly=True, anomaly_percentile=96.0, detection_count=2,
        )
        ok, reason = should_submit_alert_notification(metrics, [_make_alert()], 70)
        self.assertTrue(ok)
        self.assertIn("model_extreme_percentile", reason)

    def test_below_all_thresholds_returns_false(self):
        from backend.services.detection.alert import should_submit_alert_notification
        metrics = _make_metrics(
            threat_score=20, attack_predicted=False,
            is_anomaly=False, anomaly_percentile=50.0, detection_count=1,
        )
        ok, reason = should_submit_alert_notification(metrics, [_make_alert()], 70)
        self.assertFalse(ok)
        self.assertEqual(reason, "below_notification_threshold")


class TestTruncateMessage(unittest.TestCase):

    def test_short_message_unchanged(self):
        from backend.services.detection.alert import _truncate_message
        self.assertEqual(_truncate_message("hello", 100), "hello")

    def test_long_message_truncated_with_ellipsis(self):
        from backend.services.detection.alert import _truncate_message
        result = _truncate_message("x" * 400, 300)
        self.assertLessEqual(len(result), 300)
        self.assertTrue(result.endswith("..."))

    def test_whitespace_compacted(self):
        from backend.services.detection.alert import _truncate_message
        result = _truncate_message("hello   world", 100)
        self.assertEqual(result, "hello world")

    def test_exactly_at_limit_not_truncated(self):
        from backend.services.detection.alert import _truncate_message
        msg = "a" * 300
        result = _truncate_message(msg, 300)
        self.assertEqual(result, msg)


if __name__ == "__main__":
    unittest.main()
