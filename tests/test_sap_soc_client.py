from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

from backend.services.clients.sap_soc import SAPSOCClient


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}
        self.content = b"{}" if payload is not None else b""

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class SAPSOCClientRateLimitTests(unittest.TestCase):
    def test_429_uses_retry_after_header_before_retrying(self) -> None:
        client = SAPSOCClient(
            base_url="https://sap.example",
            token="token",
            max_retries=2,
            retry_backoff_seconds=2,
            min_request_interval_seconds=0,
        )
        fake_session = FakeSession(
            [
                FakeResponse(429, text="Too Many Requests", headers={"Retry-After": "7"}),
                FakeResponse(200, payload={"status": "ok"}),
            ]
        )
        client.session = fake_session

        with patch("backend.services.clients.sap_soc.time.sleep") as sleep_mock:
            payload = client.get_health()

        self.assertEqual(payload, {"status": "ok"})
        sleep_mock.assert_called_once_with(7.0)
        self.assertEqual(len(fake_session.calls), 2)

    def test_min_request_interval_spaces_consecutive_requests(self) -> None:
        client = SAPSOCClient(
            base_url="https://sap.example",
            token="token",
            min_request_interval_seconds=1.0,
        )
        fake_session = FakeSession(
            [
                FakeResponse(200, payload={"first": True}),
                FakeResponse(200, payload={"second": True}),
            ]
        )
        client.session = fake_session

        with patch("backend.services.clients.sap_soc.time.sleep") as sleep_mock, patch(
            "backend.services.clients.sap_soc.time.monotonic",
            Mock(side_effect=[100.0, 100.25, 101.0]),
        ):
            first = client.get_health()
            second = client.get_info()

        self.assertEqual(first, {"first": True})
        self.assertEqual(second, {"second": True})
        sleep_mock.assert_called_once_with(0.75)
        self.assertEqual(fake_session.calls[0]["url"], "https://sap.example/health")
        self.assertEqual(fake_session.calls[1]["url"], "https://sap.example/info")


if __name__ == "__main__":
    unittest.main()
