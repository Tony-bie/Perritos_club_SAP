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


if __name__ == "__main__":
    unittest.main()
