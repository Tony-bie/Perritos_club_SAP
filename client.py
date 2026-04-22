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

    def _get(
        self,
        path: str,
        params: Dict[str, Any] | None = None,
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
                response = self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.timeout_seconds,
                )

                if response.status_code in (401, 422):
                    detail = response.text
                    raise RuntimeError(f"Request failed {response.status_code}: {detail}")

                if response.status_code == 503 and attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue

                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * attempt)

        raise RuntimeError(f"Request failed after retries: {last_error}")

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
