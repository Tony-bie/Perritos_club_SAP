from __future__ import annotations

import json
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

    def test_db_host_auto_selects_hana_backend(self) -> None:
        env = {
            "DB_HOST": "railway-hana-host.example",
            "DB_PORT": "443",
            "DB_USER": "DBADMIN",
            "DB_PASSWORD": "database-password",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()

        self.assertEqual(settings.storage_backend, "hana")
        self.assertEqual(settings.hana_host, "railway-hana-host.example")
        self.assertEqual(settings.hana_user, "DBADMIN")
        self.assertEqual(settings.hana_password, "database-password")

    def test_db_env_vars_override_hana_cloud_uaa_binding_for_sql_login(self) -> None:
        vcap_services = {
            "hana-cloud": [
                {
                    "credentials": {
                        "host": "binding-host.hana.cloud",
                        "port": "443",
                        "uaa": {
                            "clientid": "uaa-client-id",
                            "clientsecret": "uaa-client-secret",
                            "url": "https://example.authentication.sap.hana.ondemand.com",
                        },
                        "url": "jdbc:sap://binding-host.hana.cloud:443?encrypt=true&validateCertificate=true",
                    }
                }
            ]
        }
        env = {
            "VCAP_APPLICATION": "{}",
            "VCAP_SERVICES": json.dumps(vcap_services),
            "DB_USER": "DBADMIN",
            "DB_PASSWORD": "database-password",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()

        self.assertEqual(settings.storage_backend, "hana")
        self.assertEqual(settings.hana_host, "binding-host.hana.cloud")
        self.assertEqual(settings.hana_user, "DBADMIN")
        self.assertEqual(settings.hana_password, "database-password")


if __name__ == "__main__":
    unittest.main()
