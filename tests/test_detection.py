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


if __name__ == "__main__":
    unittest.main()
