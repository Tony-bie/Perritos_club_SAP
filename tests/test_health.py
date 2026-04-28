from __future__ import annotations

import os
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class HealthEndpointTests(unittest.TestCase):
    def test_health_endpoint_reports_storage_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env = {
                "ENABLE_WORKER": "false",
                "STORAGE_BACKEND": "sqlite",
                "SQLITE_PATH": str(Path(tmp_dir) / "test_pipeline.db"),
            }

            with patch.dict(os.environ, env, clear=False):
                self._clear_backend_modules()
                app_module = import_module("backend.api.http.application")
                with TestClient(app_module.app) as client:
                    response = client.get("/health")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["storage_ready"])
            self.assertEqual(payload["storage_backend"], "sqlite")
            self.assertFalse(payload["worker_enabled"])

    @staticmethod
    def _clear_backend_modules() -> None:
        for module_name in list(sys.modules):
            if module_name == "backend" or module_name.startswith("backend."):
                sys.modules.pop(module_name, None)


if __name__ == "__main__":
    unittest.main()
