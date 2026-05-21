"""Tests for backend/services/clients/sap_soc.py — target >= 70%."""
import unittest
from unittest.mock import MagicMock, patch, call


def _make_client(base_url="https://sap.example.com", token="tok", max_retries=3, backoff=0):
    from backend.services.clients.sap_soc import SAPSOCClient
    return SAPSOCClient(
        base_url=base_url,
        token=token,
        timeout_seconds=5,
        max_retries=max_retries,
        retry_backoff_seconds=backoff,
    )


def _mock_response(status=200, json_data=None, content=b"{}"):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content if json_data is None else b"{}"
    resp.json.return_value = json_data or {}
    resp.text = str(json_data)
    resp.raise_for_status = MagicMock()
    return resp


class TestSAPSOCClientInit(unittest.TestCase):

    def test_strips_trailing_slash(self):
        client = _make_client(base_url="https://sap.example.com/")
        self.assertEqual(client.base_url, "https://sap.example.com")

    def test_auth_header(self):
        client = _make_client(token="my-token")
        self.assertEqual(client._auth_headers["Authorization"], "Bearer my-token")


class TestRequest(unittest.TestCase):

    def test_raises_if_no_base_url(self):
        client = _make_client(base_url="", token="tok")
        with self.assertRaises(ValueError):
            client._request("GET", "/health")

    def test_raises_if_auth_required_but_no_token(self):
        client = _make_client(token="")
        with self.assertRaises(ValueError):
            client._request("GET", "/logs", requires_auth=True)

    def test_successful_get_returns_json(self):
        client = _make_client()
        resp = _mock_response(200, {"status": "ok"})
        with patch.object(client.session, "request", return_value=resp):
            result = client._request("GET", "/health", requires_auth=False)
        self.assertEqual(result["status"], "ok")

    def test_empty_content_returns_empty_dict(self):
        client = _make_client()
        resp = _mock_response(200, content=b"")
        with patch.object(client.session, "request", return_value=resp):
            result = client._request("GET", "/health", requires_auth=False)
        self.assertEqual(result, {})

    def test_401_raises_immediately_without_retry(self):
        client = _make_client(max_retries=3)
        resp = _mock_response(401, content=b"Unauthorized")
        resp.text = "Unauthorized"
        with patch.object(client.session, "request", return_value=resp):
            with self.assertRaises(RuntimeError) as ctx:
                client._request("GET", "/logs")
        self.assertIn("401", str(ctx.exception))

    def test_422_raises_immediately(self):
        client = _make_client()
        resp = _mock_response(422)
        resp.text = "Unprocessable"
        with patch.object(client.session, "request", return_value=resp):
            with self.assertRaises(RuntimeError):
                client._request("GET", "/logs")

    def test_503_retries_then_succeeds(self):
        client = _make_client(max_retries=3, backoff=0)
        resp_503 = _mock_response(503)
        resp_ok = _mock_response(200, {"ok": True})
        with patch.object(client.session, "request", side_effect=[resp_503, resp_ok]), \
             patch("time.sleep"):
            result = client._request("GET", "/health", requires_auth=False)
        self.assertEqual(result["ok"], True)

    def test_all_retries_exhausted_raises(self):
        client = _make_client(max_retries=2, backoff=0)
        with patch.object(client.session, "request", side_effect=Exception("network error")), \
             patch("time.sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                client._request("GET", "/health", requires_auth=False)
        self.assertIn("retries", str(ctx.exception).lower())

    def test_no_auth_header_when_requires_auth_false(self):
        client = _make_client()
        resp = _mock_response(200, {})
        with patch.object(client.session, "request", return_value=resp) as mock_req:
            client._request("GET", "/health", requires_auth=False)
        call_kwargs = mock_req.call_args[1]
        self.assertEqual(call_kwargs["headers"], {})


class TestHighLevelMethods(unittest.TestCase):

    def test_get_health(self):
        client = _make_client()
        resp = _mock_response(200, {"status": "healthy"})
        with patch.object(client.session, "request", return_value=resp):
            result = client.get_health()
        self.assertEqual(result["status"], "healthy")

    def test_get_info(self):
        client = _make_client()
        resp = _mock_response(200, {"total_pages": 5, "total_records": 1000})
        with patch.object(client.session, "request", return_value=resp):
            result = client.get_info()
        self.assertEqual(result["total_pages"], 5)

    def test_get_logs_page(self):
        client = _make_client()
        resp = _mock_response(200, {"data": [{"id": 1}]})
        with patch.object(client.session, "request", return_value=resp) as mock_req:
            result = client.get_logs_page(page=2)
        params = mock_req.call_args[1]["params"]
        self.assertEqual(params["page"], 2)
        self.assertEqual(result["data"][0]["id"], 1)

    def test_fetch_current_window_all_pages_zero_pages(self):
        client = _make_client()
        with patch.object(client, "get_info", return_value={"total_pages": 0}):
            result = client.fetch_current_window_all_pages()
        self.assertEqual(result["pages"], [])
        self.assertEqual(result["records"], [])

    def test_fetch_current_window_all_pages_multiple(self):
        client = _make_client()
        info = {"total_pages": 2, "total_records": 4}
        page1 = {"data": [{"id": 1}, {"id": 2}]}
        page2 = {"data": [{"id": 3}, {"id": 4}]}
        with patch.object(client, "get_info", return_value=info), \
             patch.object(client, "get_logs_page", side_effect=[page1, page2]):
            result = client.fetch_current_window_all_pages()
        self.assertEqual(len(result["records"]), 4)
        self.assertEqual(len(result["pages"]), 2)

    def test_submit_alert_success(self):
        client = _make_client()
        resp = _mock_response(200, {"submitted": True})
        with patch.object(client.session, "request", return_value=resp):
            result = client.submit_alert("Security anomaly detected.")
        self.assertTrue(result["submitted"])

    def test_submit_alert_empty_raises(self):
        client = _make_client()
        with self.assertRaises(ValueError):
            client.submit_alert("   ")

    def test_submit_alert_long_message_truncated(self):
        client = _make_client()
        long_msg = "x" * 400
        resp = _mock_response(200, {})
        with patch.object(client.session, "request", return_value=resp) as mock_req:
            client.submit_alert(long_msg)
        body = mock_req.call_args[1]["json"]
        self.assertLessEqual(len(body["message"]), 300)
        self.assertTrue(body["message"].endswith("..."))

    def test_submit_alert_compact_whitespace(self):
        client = _make_client()
        resp = _mock_response(200, {})
        with patch.object(client.session, "request", return_value=resp) as mock_req:
            client.submit_alert("hello    world  alert")
        body = mock_req.call_args[1]["json"]
        self.assertEqual(body["message"], "hello world alert")


if __name__ == "__main__":
    unittest.main()
