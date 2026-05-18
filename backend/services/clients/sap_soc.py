from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from typing import Any, Dict, List

import requests


class SAPSOCClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        retry_backoff_seconds: int = 2,
        min_request_interval_seconds: float = 0.0,
        max_retry_after_seconds: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.min_request_interval_seconds = max(0.0, float(min_request_interval_seconds))
        self.max_retry_after_seconds = max(1, int(max_retry_after_seconds))
        self.session = requests.Session()
        self._last_request_monotonic: float | None = None

    @property
    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _request(
        self,
        method: str,
        path: str,
        params: Dict[str, Any] | None = None,
        json_body: Dict[str, Any] | None = None,
        requires_auth: bool = True,
    ) -> Dict[str, Any]:
        if not self.base_url:
            raise ValueError("SAP_SOC_BASE_URL is required")
        if requires_auth and not self.token:
            raise ValueError("SAP_SOC_TOKEN is required")

        url = f"{self.base_url}{path}"
        headers = self._auth_headers if requires_auth else {}

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._throttle_before_request()
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=self.timeout_seconds,
                )
                self._last_request_monotonic = time.monotonic()

                if response.status_code in (401, 422):
                    detail = response.text
                    raise RuntimeError(f"Request failed {response.status_code}: {detail}")

                if response.status_code in (429, 503):
                    detail = response.text
                    last_error = RuntimeError(f"Request failed {response.status_code}: {detail}")
                    if attempt < self.max_retries:
                        time.sleep(self._retry_delay_seconds(response, attempt))
                        continue

                    response.raise_for_status()
                    raise last_error

                if response.status_code >= 500 and attempt < self.max_retries:
                    last_error = RuntimeError(f"Request failed {response.status_code}: {response.text}")
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue

                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
            except Exception as exc:
                if self._last_request_monotonic is None:
                    self._last_request_monotonic = time.monotonic()
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * attempt)

        raise RuntimeError(f"Request failed after retries: {last_error}")

    def _throttle_before_request(self) -> None:
        if self.min_request_interval_seconds <= 0 or self._last_request_monotonic is None:
            return

        elapsed_seconds = time.monotonic() - self._last_request_monotonic
        remaining_seconds = self.min_request_interval_seconds - elapsed_seconds
        if remaining_seconds > 0:
            time.sleep(remaining_seconds)

    def _retry_delay_seconds(self, response: requests.Response, attempt: int) -> float:
        backoff_seconds = self.retry_backoff_seconds * attempt
        retry_after_seconds = self._retry_after_seconds(response)
        if retry_after_seconds is None:
            return backoff_seconds
        return max(backoff_seconds, min(retry_after_seconds, self.max_retry_after_seconds))

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float | None:
        raw_retry_after = response.headers.get("Retry-After")
        if not raw_retry_after:
            return None

        cleaned = raw_retry_after.strip()
        if cleaned.isdigit():
            return float(cleaned)

        try:
            retry_at = parsedate_to_datetime(cleaned)
        except (TypeError, ValueError):
            return None

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

    def _get(
        self,
        path: str,
        params: Dict[str, Any] | None = None,
        requires_auth: bool = True,
    ) -> Dict[str, Any]:
        return self._request(
            method="GET",
            path=path,
            params=params,
            requires_auth=requires_auth,
        )

    def _post_json(
        self,
        path: str,
        payload: Dict[str, Any],
        requires_auth: bool = True,
    ) -> Dict[str, Any]:
        return self._request(
            method="POST",
            path=path,
            json_body=payload,
            requires_auth=requires_auth,
        )

    def get_health(self) -> Dict[str, Any]:
        return self._get("/health", requires_auth=False)

    def get_info(self) -> Dict[str, Any]:
        return self._get("/info", requires_auth=True)

    def get_logs_page(self, page: int) -> Dict[str, Any]:
        return self._get("/logs/current", params={"page": page}, requires_auth=True)

    def fetch_current_window_all_pages(self) -> Dict[str, Any]:
        info = self.get_info()
        total_pages = int(info.get("total_pages", 0))
        if total_pages < 1:
            return {
                "info": info,
                "pages": [],
                "records": [],
            }

        pages: List[Dict[str, Any]] = []
        records: List[Dict[str, Any]] = []
        for page_number in range(1, total_pages + 1):
            payload = self.get_logs_page(page_number)
            pages.append(payload)
            records.extend(payload.get("data", []))

        return {
            "info": info,
            "pages": pages,
            "records": records,
        }

    def submit_alert(self, message: str) -> Dict[str, Any]:
        compact_message = " ".join(str(message).split()).strip()
        if not compact_message:
            raise ValueError("Alert message cannot be empty")

        if len(compact_message) > 300:
            compact_message = f"{compact_message[:297].rstrip()}..."

        return self._post_json(
            "/alert",
            payload={"message": compact_message},
            requires_auth=True,
        )
