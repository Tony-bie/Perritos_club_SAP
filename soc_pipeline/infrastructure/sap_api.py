from __future__ import annotations

from typing import Any

import requests


class SapSocClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_info(self) -> dict[str, Any]:
        return self._get("/info")

    def get_logs_page(self, page: int) -> dict[str, Any]:
        return self._get("/logs/current", params={"page": page})

    def get_all_logs(self) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        info_payload = self.get_info()
        first_page = self.get_logs_page(page=1)
        total_pages = int(first_page.get("total_pages", 1) or 1)
        records = list(first_page.get("data", []))

        for page in range(2, total_pages + 1):
            page_payload = self.get_logs_page(page=page)
            records.extend(page_payload.get("data", []))

        return records, info_payload, total_pages
