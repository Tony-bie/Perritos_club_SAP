from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.core.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_enable_worker_defaults_to_true(self) -> None:
        env_without_worker = {
            key: value
            for key, value in os.environ.items()
            if key != "ENABLE_WORKER"
        }

        with patch.dict(os.environ, env_without_worker, clear=True):
            settings = load_settings()

        self.assertTrue(settings.enable_worker)


if __name__ == "__main__":
    unittest.main()
