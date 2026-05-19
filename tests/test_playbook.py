import unittest

from backend.escalation.playbook import decide_escalation_for_alert
from types import SimpleNamespace


class PlaybookTests(unittest.TestCase):
    def test_high_severity_goes_to_soc(self):
        settings = SimpleNamespace(error_security_threshold=100, attack_score_threshold=70)
        alert = {"severity": "high", "payload": {"count": 1}}
        window = {"threat_score": 10}
        out = decide_escalation_for_alert(alert, window, settings)
        self.assertEqual(out["level"], "SOC")

    def test_count_triggers_escalation(self):
        settings = SimpleNamespace(error_security_threshold=5, attack_score_threshold=70)
        alert = {"severity": "low", "payload": {"count": 10}}
        window = {"threat_score": 1}
        out = decide_escalation_for_alert(alert, window, settings)
        self.assertEqual(out["level"], "ESCALATED")

    def test_threat_score_pending(self):
        settings = SimpleNamespace(error_security_threshold=100, attack_score_threshold=50)
        alert = {"severity": "low", "payload": {"count": 0}}
        window = {"threat_score": 60}
        out = decide_escalation_for_alert(alert, window, settings)
        self.assertEqual(out["level"], "PENDING")


if __name__ == "__main__":
    unittest.main()
