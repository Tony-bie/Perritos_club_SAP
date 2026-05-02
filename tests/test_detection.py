from __future__ import annotations

import unittest

from backend.services.detection.detect import evaluate_window_risk


class DetectionTests(unittest.TestCase):
    def test_empty_window_does_not_emit_alerts_or_threat_score(self) -> None:
        alerts, summary = evaluate_window_risk(
            normalized_records=[],
            metrics={
                "window_key": "empty-window",
                "total_records": 0,
            },
            model_signal={
                "model_available": True,
                "is_anomaly": True,
                "anomaly_score": 99.0,
                "anomaly_percentile": 100.0,
                "source": "test_model",
            },
            historical_signal={
                "historical_available": True,
                "historical_source": "robust_z:30",
                "pattern_status": "critical_anomaly",
                "pattern_reason": "possible_incomplete_window",
                "pattern_score": 100.0,
                "max_feature_deviation": 10.0,
                "pattern_signals": [
                    {
                        "feature": "total_records",
                        "severity": "critical",
                        "points": 25,
                    }
                ],
            },
        )

        self.assertEqual(alerts, [])
        self.assertEqual(summary["threat_score"], 0)
        self.assertEqual(summary["detection_count"], 0)
        self.assertFalse(summary["attack_predicted"])
        self.assertFalse(summary["is_anomaly"])
        self.assertEqual(summary["risk_level"], "no_data")
        self.assertEqual(summary["anomaly_reason"], "empty_window")

    def test_incomplete_window_emits_data_quality_alert_not_attack(self) -> None:
        alerts, summary = evaluate_window_risk(
            normalized_records=[{"_id": "1"}],
            metrics={
                "window_key": "partial-window",
                "total_records": 3921,
            },
            model_signal={
                "model_available": False,
                "source": "insufficient_history:7",
            },
            historical_signal={
                "historical_available": True,
                "historical_source": "robust_z:58",
                "pattern_status": "critical_anomaly",
                "pattern_reason": "possible_incomplete_window",
                "pattern_score": 100.0,
                "max_feature_deviation": 19.5,
                "pattern_signals": [
                    {
                        "feature": "total_records",
                        "severity": "critical",
                        "points": 25,
                    }
                ],
            },
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_type"], "DATA_QUALITY_OR_AVAILABILITY_DROP")
        self.assertEqual(alerts[0]["severity"], "high")
        self.assertEqual(summary["threat_score"], 20)
        self.assertEqual(summary["detection_count"], 1)
        self.assertFalse(summary["attack_predicted"])
        self.assertFalse(summary["is_anomaly"])
        self.assertEqual(summary["risk_level"], "data_quality")
        self.assertEqual(summary["anomaly_reason"], "possible_incomplete_window")

    def test_llm_activity_drop_emits_investigation_alert_not_attack(self) -> None:
        alerts, summary = evaluate_window_risk(
            normalized_records=[{"_id": "1"}],
            metrics={
                "window_key": "llm-drop-window",
                "total_records": 3921,
            },
            model_signal={
                "model_available": False,
                "source": "insufficient_history:7",
            },
            historical_signal={
                "historical_available": True,
                "historical_source": "robust_z:58",
                "pattern_status": "critical_anomaly",
                "pattern_reason": "llm_activity_drop",
                "pattern_score": 65.0,
                "max_feature_deviation": 12.0,
                "pattern_signals": [
                    {
                        "feature": "llm_log_count",
                        "severity": "critical",
                        "points": 25,
                        "direction": "lower_than_usual",
                    }
                ],
            },
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_type"], "LLM_ACTIVITY_DROP")
        self.assertEqual(alerts[0]["severity"], "high")
        self.assertEqual(summary["threat_score"], 20)
        self.assertEqual(summary["detection_count"], 1)
        self.assertFalse(summary["attack_predicted"])
        self.assertFalse(summary["is_anomaly"])
        self.assertEqual(summary["risk_level"], "service_activity_anomaly")
        self.assertEqual(summary["anomaly_reason"], "llm_activity_drop")

    def test_security_combinations_emit_correlation_alerts_without_history(self) -> None:
        alerts, summary = evaluate_window_risk(
            normalized_records=[{"_id": "1"}],
            metrics={
                "window_key": "security-combo-window",
                "total_records": 3921,
                "security_count": 80,
                "error_count": 452,
                "llm_error_count": 174,
                "llm_timeout_count": 75,
                "security_event_rate": 0.025,
                "system_error_rate": 0.145,
            },
            model_signal={
                "model_available": False,
                "source": "insufficient_history:7",
            },
            historical_signal={
                "historical_available": False,
                "historical_source": "insufficient_history:7",
                "pattern_status": "unknown",
                "pattern_reason": "insufficient_history",
                "pattern_score": 0.0,
                "max_feature_deviation": 0.0,
                "pattern_signals": [],
            },
        )

        alert_types = {alert["alert_type"] for alert in alerts}
        self.assertIn("SECURITY_ERROR_CORRELATION", alert_types)
        self.assertIn("SECURITY_LLM_DISRUPTION_CORRELATION", alert_types)
        self.assertEqual(summary["threat_score"], 42)
        self.assertEqual(summary["detection_count"], 2)
        self.assertFalse(summary["attack_predicted"])
        self.assertEqual(summary["risk_level"], "security_correlation")
        self.assertEqual(summary["anomaly_reason"], "security_correlation")

    def test_strong_security_combinations_can_predict_attack(self) -> None:
        alerts, summary = evaluate_window_risk(
            normalized_records=[{"_id": "1"}],
            metrics={
                "window_key": "strong-security-combo-window",
                "total_records": 5000,
                "security_count": 140,
                "error_count": 900,
                "http_4xx_count": 120,
                "http_5xx_count": 90,
                "llm_error_count": 210,
                "llm_timeout_count": 120,
                "max_events_from_single_ip": 1800,
                "top_ip_event_share": 0.36,
                "security_event_rate": 0.06,
                "system_error_rate": 0.18,
            },
            model_signal={
                "model_available": False,
                "source": "insufficient_history:7",
            },
            historical_signal={
                "historical_available": False,
                "historical_source": "insufficient_history:7",
                "pattern_status": "unknown",
                "pattern_reason": "insufficient_history",
                "pattern_score": 0.0,
                "max_feature_deviation": 0.0,
                "pattern_signals": [],
            },
        )

        alert_types = {alert["alert_type"] for alert in alerts}
        self.assertIn("SECURITY_ERROR_CORRELATION", alert_types)
        self.assertIn("SECURITY_HTTP_FAILURE_CORRELATION", alert_types)
        self.assertIn("SECURITY_SINGLE_IP_PRESSURE", alert_types)
        self.assertIn("SECURITY_LLM_DISRUPTION_CORRELATION", alert_types)
        self.assertEqual(summary["threat_score"], 98)
        self.assertTrue(summary["attack_predicted"])
        self.assertEqual(summary["risk_level"], "security_correlation")
        self.assertEqual(summary["anomaly_reason"], "security_correlation")


if __name__ == "__main__":
    unittest.main()
