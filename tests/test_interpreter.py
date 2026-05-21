"""Tests for backend/services/chatbot/interpreter.py — target >= 70%."""
import unittest
from unittest.mock import MagicMock, patch


def _make_settings(
    llm_enabled=True,
    model="groq/llama-3.1-8b-instant",
    api_key="test-key",
    base_url=None,
    temperature=0.2,
    max_tokens=400,
):
    s = MagicMock()
    s.llm_enabled = llm_enabled
    s.llm_provider_model = model
    s.llm_api_key = api_key
    s.llm_base_url = base_url
    s.llm_temperature = temperature
    s.llm_max_tokens = max_tokens
    return s


def _make_context(**overrides):
    base = {
        "summary": {
            "recent_alerts": 3,
            "high_alerts": 1,
            "anomaly_windows": 2,
            "latest_run_status": "success",
            "latest_risk_level": "medium",
            "latest_anomaly_reason": "first_observed_values",
            "fallback_pending_counts": {},
        }
    }
    base.update(overrides)
    return base


class TestFallbackResponse(unittest.TestCase):

    def test_returns_string_with_question(self):
        from backend.services.chatbot.interpreter import _fallback_response
        result = _fallback_response("¿cuántas alertas?", _make_context(), "llm_disabled")
        self.assertIsInstance(result, str)
        self.assertIn("¿cuántas alertas?", result)

    def test_includes_summary_data(self):
        from backend.services.chatbot.interpreter import _fallback_response
        result = _fallback_response("q", _make_context(), "llm_disabled")
        self.assertIn("3", result)   # recent_alerts
        self.assertIn("success", result)

    def test_includes_reason(self):
        from backend.services.chatbot.interpreter import _fallback_response
        result = _fallback_response("q", _make_context(), "litellm_not_installed")
        self.assertIn("litellm_not_installed", result)

    def test_empty_context_does_not_crash(self):
        from backend.services.chatbot.interpreter import _fallback_response
        result = _fallback_response("q", {}, "no_reason")
        self.assertIsInstance(result, str)


class TestBuildMessages(unittest.TestCase):

    def test_returns_two_messages(self):
        from backend.services.chatbot.interpreter import _build_messages
        msgs = _build_messages("question", {"data": 1})
        self.assertEqual(len(msgs), 2)

    def test_has_system_and_user_roles(self):
        from backend.services.chatbot.interpreter import _build_messages
        msgs = _build_messages("q", {})
        roles = {m["role"] for m in msgs}
        self.assertIn("system", roles)
        self.assertIn("user", roles)

    def test_question_is_in_user_message(self):
        from backend.services.chatbot.interpreter import _build_messages
        msgs = _build_messages("¿cuántas alertas hay?", {})
        user_msg = next(m for m in msgs if m["role"] == "user")
        self.assertIn("¿cuántas alertas hay?", user_msg["content"])

    def test_context_is_serialized(self):
        from backend.services.chatbot.interpreter import _build_messages
        msgs = _build_messages("q", {"key": "value123"})
        user_msg = next(m for m in msgs if m["role"] == "user")
        self.assertIn("value123", user_msg["content"])

    def test_complex_context_serialized_with_default_str(self):
        from backend.services.chatbot.interpreter import _build_messages
        from datetime import datetime
        msgs = _build_messages("q", {"ts": datetime(2026, 5, 21)})
        user_msg = next(m for m in msgs if m["role"] == "user")
        self.assertIn("2026", user_msg["content"])


class TestGenerateChatbotResponse(unittest.TestCase):

    def test_llm_disabled_returns_fallback(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        result = generate_chatbot_response("q", _make_context(), _make_settings(llm_enabled=False))
        self.assertEqual(result["source"], "fallback")
        self.assertIn("text", result)

    def test_missing_model_returns_fallback(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        mock_completion = MagicMock()  # non-None completion so we reach the model check
        with patch("backend.services.chatbot.interpreter.completion", mock_completion):
            result = generate_chatbot_response("q", _make_context(), _make_settings(model=None))
        self.assertEqual(result["source"], "fallback")
        self.assertIn("missing_model_name", result["text"])

    def test_llm_success_returns_llm_source(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "El sistema está estable."
        with patch("backend.services.chatbot.interpreter.completion", return_value=mock_resp):
            result = generate_chatbot_response("q", _make_context(), _make_settings())
        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["text"], "El sistema está estable.")

    def test_llm_exception_returns_fallback(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        with patch("backend.services.chatbot.interpreter.completion", side_effect=Exception("timeout")):
            result = generate_chatbot_response("q", _make_context(), _make_settings())
        self.assertEqual(result["source"], "fallback")
        self.assertIn("llm_error", result["text"])

    def test_empty_llm_response_returns_fallback(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "   "
        with patch("backend.services.chatbot.interpreter.completion", return_value=mock_resp):
            result = generate_chatbot_response("q", _make_context(), _make_settings())
        self.assertEqual(result["source"], "fallback")
        self.assertIn("empty_llm_response", result["text"])

    def test_none_choices_returns_fallback(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        mock_resp = MagicMock()
        mock_resp.choices = None
        with patch("backend.services.chatbot.interpreter.completion", return_value=mock_resp):
            result = generate_chatbot_response("q", _make_context(), _make_settings())
        self.assertEqual(result["source"], "fallback")

    def test_api_key_passed_when_present(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "ok"
        with patch("backend.services.chatbot.interpreter.completion", return_value=mock_resp) as mock_c:
            generate_chatbot_response("q", {}, _make_settings(api_key="my-key"))
        kwargs = mock_c.call_args[1]
        self.assertEqual(kwargs.get("api_key"), "my-key")

    def test_base_url_passed_when_present(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "ok"
        with patch("backend.services.chatbot.interpreter.completion", return_value=mock_resp) as mock_c:
            generate_chatbot_response("q", {}, _make_settings(base_url="http://proxy"))
        kwargs = mock_c.call_args[1]
        self.assertEqual(kwargs.get("api_base"), "http://proxy")

    def test_completion_none_returns_fallback(self):
        from backend.services.chatbot.interpreter import generate_chatbot_response
        with patch("backend.services.chatbot.interpreter.completion", None):
            result = generate_chatbot_response("q", _make_context(), _make_settings())
        self.assertEqual(result["source"], "fallback")
        self.assertIn("litellm_not_installed", result["text"])


if __name__ == "__main__":
    unittest.main()
