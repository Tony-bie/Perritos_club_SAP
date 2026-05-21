"""
Tests for backend/telegram/messages.py — target >= 90% coverage.

Note: lines 16-23 (ModuleNotFoundError branch) and 38-41 (invalid token
branch) are module-level code executed at import time and cannot be covered
without uninstalling aiogram or injecting an invalid token before import.
Everything else is covered here.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from html import escape


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_message(text="/metrics_windows 3", chat_id=999):
    msg = MagicMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.answer = AsyncMock()
    return msg


def _make_window(index=1, **overrides):
    base = {
        "window_start": f"2026-05-21T0{index}:00:00+00:00",
        "window_end":   f"2026-05-21T0{index}:30:00+00:00",
        "total_records": 5521,
        "system_log_count": 3254,
        "llm_log_count": 2267,
        "error_count": 480,
        "security_count": 83,
        "warning_count": 621,
        "unique_client_ips": 105,
        "unique_services": 8,
        "http_4xx_count": 511,
        "http_5xx_count": 276,
        "llm_request_count": 1535,
        "llm_error_rate": 0.21,
        "llm_timeout_rate": 0.11,
        "avg_llm_latency_ms": 9013.0,
        "p95_llm_latency_ms": 31760.0,
        "total_llm_cost_usd": 27.16,
        "risk_level": "novel_activity",
        "threat_score": 30,
        "is_anomaly": True,
        "anomaly_reason": "first_observed_values",
        # large arrays that used to blow up the old handler
        "observed_log_types": ["AUDIT", "ERROR", "INFO"] * 20,
        "observed_client_ips": ["1.2.3.4"] * 50,
        "observed_service_ids": ["svc"] * 10,
        "observed_http_status_codes": ["200", "500"] * 10,
        "observed_llm_model_ids": ["claude-3-5-haiku"] * 30,
        "novelty_signals": [{"field": f"f{n}", "values": list(range(20)), "points": 10} for n in range(10)],
    }
    base.update(overrides)
    return base


def _make_alert(index=1):
    return {
        "alert_type": f"security_spike_{index}",
        "severity": "high",
        "detected_at_utc": "2026-05-21T01:30:00+00:00",
        "payload": {
            "score": 85,
            "payload": {
                "security_count": 83,
                "error_count": 480,
                "security_event_rate": 0.025,
                "system_error_rate": 0.147,
            },
        },
    }


def _make_run(index=1):
    return {
        "run_id": f"run-{index}",
        "status": "success",
        "started_at_utc": "2026-05-21T01:45:36+00:00",
        "ended_at_utc": "2026-05-21T01:45:50+00:00",
        "duration_seconds": 14.6,
        "total_records_fetched": 5521,
    }


def _make_dashboard_result(risk="LOW"):
    return {
        "total_alerts": 2,
        "alerts_by_severity": {"high": 0, "medium": 1, "low": 1},
        "top_metrics": {
            "window_start": "2026-05-21T00:00:00+00:00",
            "window_end": "2026-05-21T01:00:00+00:00",
            "risk_level": risk,
            "threat_score": 30,
            "total_records": 5521,
            "unique_client_ips": 105,
            "unique_services": 8,
            "llm_request_count": 1535,
            "llm_error_rate": 0.21,
            "llm_error_count": 478,
            "llm_timeout_rate": 0.11,
            "llm_timeout_count": 254,
            "avg_llm_latency_ms": 9013.0,
            "p95_llm_latency_ms": 31760.0,
            "total_llm_cost_usd": 27.16,
            "http_4xx_count": 511,
            "http_5xx_count": 276,
            "is_anomaly": True,
            "anomaly_reason": "first_observed_values",
            "anomaly_score": 30,
        },
        "last_run": {"status": "success", "duration_seconds": 14.6},
    }


# ---------------------------------------------------------------------------
# _build_window_block
# ---------------------------------------------------------------------------

class TestBuildWindowBlock(unittest.TestCase):

    def _block(self, **kw):
        from backend.telegram.messages import _build_window_block
        return _build_window_block(1, _make_window(**kw))

    def test_block_under_telegram_limit(self):
        block = self._block()
        self.assertLess(len(block), 4096, f"Block too long: {len(block)}")

    def test_three_blocks_each_under_limit(self):
        from backend.telegram.messages import _build_window_block
        for i in range(1, 4):
            block = _build_window_block(i, _make_window(index=i))
            self.assertLess(len(block), 4096)

    def test_block_contains_key_fields(self):
        block = self._block()
        self.assertIn("Ventana #1", block)
        self.assertIn("5,521", block)
        self.assertIn("105", block)
        self.assertIn("21.0%", block)
        self.assertIn("NOVEL_ACTIVITY", block)

    def test_block_excludes_raw_arrays(self):
        block = self._block()
        self.assertNotIn("observed_log_types", block)
        self.assertNotIn("observed_client_ips", block)
        self.assertNotIn("novelty_signals", block)

    def test_block_handles_none_values_gracefully(self):
        block = self._block(risk_level=None, anomaly_reason=None, avg_llm_latency_ms=None)
        self.assertIn("Ventana #1", block)

    def test_block_handles_zero_values(self):
        block = self._block(total_records=0, error_count=0, llm_req=0,
                            llm_error_rate=0.0, avg_llm_latency_ms=0.0,
                            p95_llm_latency_ms=0.0, total_llm_cost_usd=0.0)
        self.assertIn("Ventana #1", block)

    def test_risk_icons(self):
        from backend.telegram.messages import _build_window_block
        icons = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢", "SUSPICIOUS": "⚠️"}
        for risk, icon in icons.items():
            block = _build_window_block(1, _make_window(risk_level=risk))
            self.assertIn(icon, block)


# ---------------------------------------------------------------------------
# _send_chunked_html_messages
# ---------------------------------------------------------------------------

class TestSendChunkedHtmlMessages(unittest.TestCase):

    def _chunker(self):
        from backend.telegram.messages import _send_chunked_html_messages
        return _send_chunked_html_messages

    def _run_chunker(self, header, blocks):
        sent = []
        mock_send = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
        with patch("backend.telegram.messages.bot") as mock_bot:
            mock_bot.send_message = mock_send
            _run(self._chunker()(chat_id=123, header=header, blocks=blocks))
        return sent

    def test_three_small_blocks_fit_in_one_message(self):
        from backend.telegram.messages import _build_window_block
        blocks = [_build_window_block(i, _make_window(index=i)) for i in range(1, 4)]
        sent = self._run_chunker("<b>Header</b>", blocks)
        combined = "".join(sent)
        for i in range(1, 4):
            self.assertIn(f"Ventana #{i}", combined)
        for msg in sent:
            self.assertLessEqual(len(msg), 4096)

    def test_giant_block_is_truncated_not_crashed(self):
        sent = self._run_chunker("Header", ["x" * 5000])
        self.assertTrue(sent)
        for msg in sent:
            self.assertLessEqual(len(msg), 4096)
        self.assertTrue(any("truncado" in m for m in sent))

    def test_no_message_sent_when_bot_is_none(self):
        from backend.telegram.messages import _send_chunked_html_messages
        with patch("backend.telegram.messages.bot", None):
            _run(_send_chunked_html_messages(chat_id=123, header="H", blocks=["b"]))

    def test_many_blocks_split_across_multiple_messages(self):
        from backend.telegram.messages import _build_window_block
        blocks = [_build_window_block(i, _make_window(index=i % 9 + 1)) for i in range(1, 11)]
        sent = self._run_chunker("<b>Header</b>", blocks)
        self.assertGreater(len(sent), 1)
        for msg in sent:
            self.assertLessEqual(len(msg), 4096)

    def test_sleep_called_on_third_send(self):
        """asyncio.sleep(0.5) must be called when a 3rd message is sent."""
        # Use blocks ~2000 chars each so 2 blocks per message → 3 messages for 5 blocks
        big_block = "A" * 2000
        blocks = [big_block] * 5

        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_bot.send_message = AsyncMock()
            _run(self._chunker()(chat_id=123, header="H", blocks=blocks))

        mock_sleep.assert_called()

    def test_empty_blocks_sends_header(self):
        sent = self._run_chunker("<b>Solo header</b>", [])
        self.assertEqual(len(sent), 1)
        self.assertIn("Solo header", sent[0])


# ---------------------------------------------------------------------------
# last_status_telegram
# ---------------------------------------------------------------------------

class TestLastStatusHandler(unittest.TestCase):

    def test_happy_path_sends_formatted_message(self):
        from backend.telegram.messages import last_status_telegram
        msg = _make_message("/last_status")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.status_latest", return_value={"status": "ok", "run_id": "abc"}):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(last_status_telegram(msg))
        self.assertTrue(sent)
        self.assertIn("Estado del Sistema", sent[0])

    def test_bot_none_calls_answer(self):
        from backend.telegram.messages import last_status_telegram
        msg = _make_message("/last_status")
        with patch("backend.telegram.messages.bot", None), \
             patch("backend.api.http.status_latest", return_value={}):
            _run(last_status_telegram(msg))
        msg.answer.assert_called_once()


# ---------------------------------------------------------------------------
# health_telegram
# ---------------------------------------------------------------------------

class TestHealthHandler(unittest.TestCase):

    def test_happy_path(self):
        from backend.telegram.messages import health_telegram
        msg = _make_message("/health")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.health", new_callable=AsyncMock,
                   return_value={"status": "ok", "storage": "sqlite"}):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(health_telegram(msg))
        self.assertTrue(sent)

    def test_bot_none_calls_answer(self):
        from backend.telegram.messages import health_telegram
        msg = _make_message("/health")
        with patch("backend.telegram.messages.bot", None):
            _run(health_telegram(msg))
        msg.answer.assert_called_once()

    def test_exception_sends_error_message(self):
        from backend.telegram.messages import health_telegram
        msg = _make_message("/health")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.health", new_callable=AsyncMock,
                   side_effect=RuntimeError("db down")):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(health_telegram(msg))
        self.assertTrue(any("Error" in m for m in sent))


# ---------------------------------------------------------------------------
# alerts_recent handler
# ---------------------------------------------------------------------------

class TestAlertsRecentHandler(unittest.TestCase):

    def _run_handler(self, alerts, cmd="/alerts_recent 3"):
        from backend.telegram.messages import alert_recent_telegram
        msg = _make_message(cmd)
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.alerts_recent", return_value=alerts):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(alert_recent_telegram(msg))
        return sent

    def test_happy_path_three_alerts(self):
        sent = self._run_handler([_make_alert(i) for i in range(1, 4)])
        combined = "".join(sent)
        self.assertIn("Alertas Recientes", combined)
        self.assertIn("security_spike_1", combined)

    def test_empty_alerts(self):
        sent = self._run_handler([])
        self.assertTrue(sent)

    def test_default_limit(self):
        from backend.telegram.messages import alert_recent_telegram
        msg = _make_message("/alerts_recent")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.alerts_recent", return_value=[]) as mock_api:
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(alert_recent_telegram(msg))
        mock_api.assert_called_with(limit=3)

    def test_bot_none_calls_answer(self):
        from backend.telegram.messages import alert_recent_telegram
        msg = _make_message("/alerts_recent")
        with patch("backend.telegram.messages.bot", None):
            _run(alert_recent_telegram(msg))
        msg.answer.assert_called_once()

    def test_exception_sends_error(self):
        from backend.telegram.messages import alert_recent_telegram
        msg = _make_message("/alerts_recent 3")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.alerts_recent", side_effect=RuntimeError("boom")):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(alert_recent_telegram(msg))
        self.assertTrue(any("rango" in m.lower() or "error" in m.lower() for m in sent))


# ---------------------------------------------------------------------------
# metrics_windows handler
# ---------------------------------------------------------------------------

class TestMetricsWindowsHandler(unittest.TestCase):

    def _run_handler(self, n_windows, cmd="/metrics_windows 3"):
        from backend.telegram.messages import metrics_windows_telegram
        msg = _make_message(cmd)
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.metrics_windows",
                   return_value=[_make_window(index=i % 9 + 1) for i in range(n_windows)]):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(metrics_windows_telegram(msg))
        return sent

    def test_three_windows_all_present(self):
        sent = self._run_handler(3)
        combined = "".join(sent)
        for i in range(1, 4):
            self.assertIn(f"Ventana #{i}", combined)
        for msg in sent:
            self.assertLessEqual(len(msg), 4096)

    def test_one_window(self):
        sent = self._run_handler(1, "/metrics_windows 1")
        combined = "".join(sent)
        self.assertIn("Ventana #1", combined)
        self.assertNotIn("Ventana #2", combined)

    def test_default_limit_is_3(self):
        sent = self._run_handler(3, "/metrics_windows")
        combined = "".join(sent)
        for i in range(1, 4):
            self.assertIn(f"Ventana #{i}", combined)

    def test_empty_result_sends_header(self):
        sent = self._run_handler(0)
        self.assertTrue(sent)

    def test_ten_windows_all_under_limit(self):
        sent = self._run_handler(10, "/metrics_windows 10")
        combined = "".join(sent)
        for i in range(1, 11):
            self.assertIn(f"Ventana #{i}", combined)
        for msg in sent:
            self.assertLessEqual(len(msg), 4096)

    def test_bot_none_calls_answer(self):
        from backend.telegram.messages import metrics_windows_telegram
        msg = _make_message("/metrics_windows 3")
        with patch("backend.telegram.messages.bot", None):
            _run(metrics_windows_telegram(msg))
        msg.answer.assert_called_once()

    def test_exception_sends_error(self):
        from backend.telegram.messages import metrics_windows_telegram
        msg = _make_message("/metrics_windows 3")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.metrics_windows", side_effect=RuntimeError("boom")):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(metrics_windows_telegram(msg))
        self.assertTrue(any("Error" in m or "error" in m for m in sent))


# ---------------------------------------------------------------------------
# runs_recent handler
# ---------------------------------------------------------------------------

class TestRunsRecentHandler(unittest.TestCase):

    def _run_handler(self, runs, cmd="/runs_recent 3"):
        from backend.telegram.messages import run_recent_telegram
        msg = _make_message(cmd)
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.runs_recent", return_value=runs):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(run_recent_telegram(msg))
        return sent

    def test_happy_path(self):
        sent = self._run_handler([_make_run(i) for i in range(1, 4)])
        combined = "".join(sent)
        self.assertIn("Historial reciente", combined)
        self.assertIn("run-1", combined)

    def test_empty_runs(self):
        sent = self._run_handler([])
        self.assertTrue(sent)

    def test_run_with_none_and_float_values(self):
        run = {"status": None, "duration_seconds": 14.5678, "started_at_utc": "2026-05-21T01:00:00"}
        sent = self._run_handler([run])
        self.assertTrue(sent)

    def test_bot_none_calls_answer(self):
        from backend.telegram.messages import run_recent_telegram
        msg = _make_message("/runs_recent")
        with patch("backend.telegram.messages.bot", None):
            _run(run_recent_telegram(msg))
        msg.answer.assert_called_once()

    def test_exception_sends_error(self):
        from backend.telegram.messages import run_recent_telegram
        msg = _make_message("/runs_recent 3")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.runs_recent", side_effect=RuntimeError("boom")):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(run_recent_telegram(msg))
        self.assertTrue(sent)


# ---------------------------------------------------------------------------
# dashboard handler
# ---------------------------------------------------------------------------

class TestDashboardHandler(unittest.TestCase):

    def _run_handler(self, result, cmd="/dashboard 24"):
        from backend.telegram.messages import dashboard_telegram
        msg = _make_message(cmd)
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.dashboard_summary", return_value=result):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(dashboard_telegram(msg))
        return sent

    def test_happy_path_low_risk(self):
        sent = self._run_handler(_make_dashboard_result("LOW"))
        combined = "".join(sent)
        self.assertIn("Security Dashboard", combined)
        self.assertIn("🟢", combined)

    def test_high_risk_icon(self):
        sent = self._run_handler(_make_dashboard_result("HIGH"))
        self.assertIn("🔴", "".join(sent))

    def test_medium_risk_icon(self):
        sent = self._run_handler(_make_dashboard_result("MEDIUM"))
        self.assertIn("🟡", "".join(sent))

    def test_suspicious_risk_icon(self):
        sent = self._run_handler(_make_dashboard_result("SUSPICIOUS"))
        self.assertIn("⚠️", "".join(sent))

    def test_bot_none_calls_answer(self):
        from backend.telegram.messages import dashboard_telegram
        msg = _make_message("/dashboard 24")
        with patch("backend.telegram.messages.bot", None):
            _run(dashboard_telegram(msg))
        msg.answer.assert_called_once()

    def test_exception_sends_error(self):
        from backend.telegram.messages import dashboard_telegram
        msg = _make_message("/dashboard 24")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.dashboard_summary", side_effect=RuntimeError("boom")):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(dashboard_telegram(msg))
        self.assertTrue(any("Error" in m or "error" in m.lower() for m in sent))

    def test_value_error_sends_hint(self):
        from backend.telegram.messages import dashboard_telegram
        msg = _make_message("/dashboard 24")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot, \
             patch("backend.api.http.dashboard_summary", side_effect=ValueError("bad")):
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(dashboard_telegram(msg))
        self.assertTrue(any("válido" in m or "dashboard" in m.lower() for m in sent))


# ---------------------------------------------------------------------------
# start handler
# ---------------------------------------------------------------------------

class TestStartHandler(unittest.TestCase):

    def test_happy_path_sends_command_list(self):
        from backend.telegram.messages import start
        msg = _make_message("/start")
        sent = []
        with patch("backend.telegram.messages.bot") as mock_bot:
            mock_bot.send_message = AsyncMock(side_effect=lambda **kw: sent.append(kw["text"]))
            _run(start(msg))
        combined = "".join(sent)
        self.assertIn("Perritos Assistant", combined)
        self.assertIn("/health", combined)
        self.assertIn("/dashboard", combined)

    def test_bot_none_calls_answer(self):
        from backend.telegram.messages import start
        msg = _make_message("/start")
        with patch("backend.telegram.messages.bot", None):
            _run(start(msg))
        msg.answer.assert_called_once()


# ---------------------------------------------------------------------------
# ask_telegram handler
# ---------------------------------------------------------------------------

class TestAskHandler(unittest.TestCase):

    def test_delegates_to_handle_telegram_analysis(self):
        from backend.telegram.messages import ask_telegram
        msg = _make_message("/ask cuantas alertas hay?")
        with patch("backend.api.http._extract_command_argument", return_value="cuantas alertas hay?"), \
             patch("backend.api.http._handle_telegram_analysis", new_callable=AsyncMock) as mock_handle:
            _run(ask_telegram(msg))
        mock_handle.assert_called_once()
        _, question = mock_handle.call_args[0]
        self.assertEqual(question, "cuantas alertas hay?")

    def test_empty_question(self):
        from backend.telegram.messages import ask_telegram
        msg = _make_message("/ask")
        with patch("backend.api.http._extract_command_argument", return_value=""), \
             patch("backend.api.http._handle_telegram_analysis", new_callable=AsyncMock) as mock_handle:
            _run(ask_telegram(msg))
        mock_handle.assert_called_once()


# ---------------------------------------------------------------------------
# free_text_telegram handler
# ---------------------------------------------------------------------------

class TestFreeTextHandler(unittest.TestCase):

    def test_plain_text_triggers_analysis(self):
        from backend.telegram.messages import free_text_telegram
        msg = _make_message("cuantas alertas hay?")
        with patch("backend.api.http._handle_telegram_analysis", new_callable=AsyncMock) as mock_handle:
            _run(free_text_telegram(msg))
        mock_handle.assert_called_once()

    def test_slash_command_is_skipped(self):
        from backend.telegram.messages import free_text_telegram
        msg = _make_message("/health")
        with patch("backend.api.http._handle_telegram_analysis", new_callable=AsyncMock) as mock_handle:
            _run(free_text_telegram(msg))
        mock_handle.assert_not_called()

    def test_empty_text_is_skipped(self):
        from backend.telegram.messages import free_text_telegram
        msg = _make_message("")
        with patch("backend.api.http._handle_telegram_analysis", new_callable=AsyncMock) as mock_handle:
            _run(free_text_telegram(msg))
        mock_handle.assert_not_called()


# ---------------------------------------------------------------------------
# run_bot
# ---------------------------------------------------------------------------

class TestRunBot(unittest.TestCase):

    def test_starts_polling_when_configured(self):
        from backend.telegram.messages import run_bot
        mock_dp = MagicMock()
        mock_dp.start_polling = AsyncMock()
        mock_bot = MagicMock()
        with patch("backend.telegram.messages.dp", mock_dp), \
             patch("backend.telegram.messages.bot", mock_bot):
            _run(run_bot())
        mock_dp.start_polling.assert_called_once_with(mock_bot)

    def test_does_nothing_when_dp_is_none(self):
        from backend.telegram.messages import run_bot
        with patch("backend.telegram.messages.dp", None), \
             patch("backend.telegram.messages.bot", MagicMock()):
            _run(run_bot())  # must not raise

    def test_does_nothing_when_bot_is_none(self):
        from backend.telegram.messages import run_bot
        mock_dp = MagicMock()
        mock_dp.start_polling = AsyncMock()
        with patch("backend.telegram.messages.dp", mock_dp), \
             patch("backend.telegram.messages.bot", None):
            _run(run_bot())
        mock_dp.start_polling.assert_not_called()


if __name__ == "__main__":
    unittest.main()
