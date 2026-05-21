"""
HTTP client for the SAP SOC API with retry and auth support.

Handles Bearer token auth, pagination, and exponential backoff.
401/422 raise immediately. 503 retries up to max_retries times.
Main method: fetch_current_window_all_pages() to get all logs at once.
"""
from __future__ import annotations

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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.session = requests.Session()

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
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=self.timeout_seconds,
                )

                if response.status_code in (401, 422):
                    detail = response.text
                    raise RuntimeError(f"Request failed {response.status_code}: {detail}")

                if response.status_code == 503 and attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue

                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * attempt)

        raise RuntimeError(f"Request failed after retries: {last_error}")

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
