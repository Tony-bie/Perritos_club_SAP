"""Extended tests for backend/core/config.py — target >= 95%."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch


class TestGetOauthToken(unittest.TestCase):

    def test_returns_access_token_on_success(self):
        from backend.core.config import _get_oauth_token
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "tok-123"}
        mock_resp.raise_for_status = MagicMock()
        with patch("backend.core.config.requests") as mock_req:
            mock_req.post.return_value = mock_resp
            result = _get_oauth_token("https://uaa.example.com", "clientid", "secret")
        self.assertEqual(result, "tok-123")

    def test_returns_empty_on_exception(self):
        from backend.core.config import _get_oauth_token
        with patch("backend.core.config.requests") as mock_req:
            mock_req.post.side_effect = Exception("network error")
            result = _get_oauth_token("https://uaa.example.com", "cid", "secret")
        self.assertEqual(result, "")

    def test_returns_empty_when_requests_none(self):
        from backend.core.config import _get_oauth_token
        with patch("backend.core.config.requests", None):
            result = _get_oauth_token("https://uaa.example.com", "cid", "secret")
        self.assertEqual(result, "")

    def test_returns_empty_when_access_token_missing(self):
        from backend.core.config import _get_oauth_token
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch("backend.core.config.requests") as mock_req:
            mock_req.post.return_value = mock_resp
            result = _get_oauth_token("https://uaa.example.com", "cid", "secret")
        self.assertEqual(result, "")


class TestLoadLocalEnvFallback(unittest.TestCase):

    def test_skips_on_cloud_foundry(self):
        from backend.core.config import _load_local_env_fallback
        with patch("backend.core.config._is_cloud_foundry_runtime", return_value=True):
            _load_local_env_fallback()  # must not crash

    def test_skips_when_no_env_file(self):
        from backend.core.config import _load_local_env_fallback
        with patch("backend.core.config._is_cloud_foundry_runtime", return_value=False), \
             patch("backend.core.config.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            _load_local_env_fallback()

    def test_loads_key_value_from_env_file(self):
        from backend.core.config import _load_local_env_fallback
        env_content = "MY_TEST_VAR_XYZ=hello_world\n# comment\n\nEMPTY_LINE=\n"
        with patch("backend.core.config._is_cloud_foundry_runtime", return_value=False), \
             patch("backend.core.config.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.read_text.return_value = env_content
            # Ensure var isn't set before
            os.environ.pop("MY_TEST_VAR_XYZ", None)
            _load_local_env_fallback()
            self.assertEqual(os.environ.get("MY_TEST_VAR_XYZ"), "hello_world")
            os.environ.pop("MY_TEST_VAR_XYZ", None)


class TestToBool(unittest.TestCase):

    def test_none_returns_default(self):
        from backend.core.config import _to_bool
        self.assertFalse(_to_bool(None))
        self.assertTrue(_to_bool(None, default=True))

    def test_true_values(self):
        from backend.core.config import _to_bool
        for val in ["true", "1", "yes", "on", "TRUE", "YES"]:
            self.assertTrue(_to_bool(val), f"Expected True for {val!r}")

    def test_false_values(self):
        from backend.core.config import _to_bool
        for val in ["false", "0", "no", "off"]:
            self.assertFalse(_to_bool(val))


class TestToInt(unittest.TestCase):

    def test_valid_int_string(self):
        from backend.core.config import _to_int
        self.assertEqual(_to_int("42", 0), 42)

    def test_invalid_returns_default(self):
        from backend.core.config import _to_int
        self.assertEqual(_to_int("not-a-number", 99), 99)

    def test_none_returns_default(self):
        from backend.core.config import _to_int
        self.assertEqual(_to_int(None, 5), 5)


class TestToFloat(unittest.TestCase):

    def test_valid_float_string(self):
        from backend.core.config import _to_float
        self.assertAlmostEqual(_to_float("3.14", 0.0), 3.14)

    def test_invalid_returns_default(self):
        from backend.core.config import _to_float
        self.assertAlmostEqual(_to_float("bad", 0.5), 0.5)

    def test_none_returns_default(self):
        from backend.core.config import _to_float
        self.assertAlmostEqual(_to_float(None, 1.0), 1.0)


class TestToIntList(unittest.TestCase):

    def test_valid_list(self):
        from backend.core.config import _to_int_list
        self.assertEqual(_to_int_list("1,2,3"), [1, 2, 3])

    def test_invalid_entry_skipped(self):
        from backend.core.config import _to_int_list
        result = _to_int_list("1,bad,3")
        self.assertEqual(result, [1, 3])

    def test_empty_string(self):
        from backend.core.config import _to_int_list
        self.assertEqual(_to_int_list(""), [])

    def test_empty_pieces_skipped(self):
        from backend.core.config import _to_int_list
        result = _to_int_list("1,,2")
        self.assertEqual(result, [1, 2])


class TestGetVcapHanaCredentials(unittest.TestCase):

    def test_no_vcap_services_returns_empty(self):
        from backend.core.config import _get_vcap_hana_credentials
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VCAP_SERVICES", None)
            result = _get_vcap_hana_credentials()
        self.assertEqual(result, {})

    def test_invalid_json_returns_empty(self):
        from backend.core.config import _get_vcap_hana_credentials
        with patch.dict(os.environ, {"VCAP_SERVICES": "not-json"}):
            result = _get_vcap_hana_credentials()
        self.assertEqual(result, {})

    def test_empty_hana_cloud_returns_empty(self):
        from backend.core.config import _get_vcap_hana_credentials
        vcap = json.dumps({"other-service": []})
        with patch.dict(os.environ, {"VCAP_SERVICES": vcap}):
            result = _get_vcap_hana_credentials()
        self.assertEqual(result, {})

    def test_credentials_not_dict_returns_empty(self):
        from backend.core.config import _get_vcap_hana_credentials
        vcap = json.dumps({"hana-cloud": [{"credentials": "not-a-dict"}]})
        with patch.dict(os.environ, {"VCAP_SERVICES": vcap}):
            result = _get_vcap_hana_credentials()
        self.assertEqual(result, {})

    def test_valid_credentials_extracted(self):
        from backend.core.config import _get_vcap_hana_credentials
        vcap = json.dumps({"hana-cloud": [{"credentials": {
            "host": "hana.example.com",
            "port": "443",
            "user": "DBUSER",
            "password": "secret",
            "schema": "MYSCHEMA",
        }}]})
        with patch.dict(os.environ, {"VCAP_SERVICES": vcap}):
            result = _get_vcap_hana_credentials()
        self.assertEqual(result.get("host"), "hana.example.com")
        self.assertEqual(result.get("user"), "DBUSER")

    def test_jdbc_url_parsed_for_host_port(self):
        from backend.core.config import _get_vcap_hana_credentials
        vcap = json.dumps({"hana-cloud": [{"credentials": {
            "url": "jdbc:sap://hana.example.com:443?encrypt=true&validateCertificate=false",
        }}]})
        with patch.dict(os.environ, {"VCAP_SERVICES": vcap}):
            result = _get_vcap_hana_credentials()
        self.assertEqual(result.get("host"), "hana.example.com")
        self.assertEqual(result.get("port"), "443")

    def test_hostname_field_maps_to_host(self):
        from backend.core.config import _get_vcap_hana_credentials
        vcap = json.dumps({"hana-cloud": [{"credentials": {
            "hostname": "hana2.example.com",
        }}]})
        with patch.dict(os.environ, {"VCAP_SERVICES": vcap}):
            result = _get_vcap_hana_credentials()
        self.assertEqual(result.get("host"), "hana2.example.com")


class TestResolvePollIntervalMinutes(unittest.TestCase):

    def test_minutes_env_var(self):
        from backend.core.config import _resolve_poll_interval_minutes
        with patch.dict(os.environ, {"POLL_INTERVAL_MINUTES": "15"}):
            result = _resolve_poll_interval_minutes()
        self.assertEqual(result, 15)

    def test_legacy_seconds_env_var(self):
        from backend.core.config import _resolve_poll_interval_minutes
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("POLL_INTERVAL_MINUTES", "SAP_SOC_POLL_SECONDS")}
        with patch.dict(os.environ, {**clean_env, "SAP_SOC_POLL_SECONDS": "1800"}, clear=True):
            result = _resolve_poll_interval_minutes()
        self.assertEqual(result, 30)

    def test_default_is_30(self):
        from backend.core.config import _resolve_poll_interval_minutes
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("POLL_INTERVAL_MINUTES", "SAP_SOC_POLL_SECONDS")}
        with patch.dict(os.environ, clean_env, clear=True):
            result = _resolve_poll_interval_minutes()
        self.assertEqual(result, 30)

    def test_minimum_poll_interval_clamped_to_1(self):
        from backend.core.config import _resolve_poll_interval_minutes
        with patch.dict(os.environ, {"POLL_INTERVAL_MINUTES": "0"}):
            result = _resolve_poll_interval_minutes()
        self.assertGreaterEqual(result, 1)


class TestGetHanaValue(unittest.TestCase):

    def test_direct_env_var_wins(self):
        from backend.core.config import _get_hana_value
        with patch.dict(os.environ, {"HANA_HOST": "direct-host"}):
            result = _get_hana_value("HANA_HOST", default="fallback")
        self.assertEqual(result, "direct-host")

    def test_returns_default_when_nothing_set(self):
        from backend.core.config import _get_hana_value
        clean_env = {k: v for k, v in os.environ.items() if "HANA" not in k}
        with patch.dict(os.environ, clean_env, clear=True), \
             patch("backend.core.config._get_vcap_hana_credentials", return_value={}), \
             patch("backend.core.config._is_cloud_foundry_runtime", return_value=False):
            result = _get_hana_value("HANA_HOST", default="mydefault")
        self.assertEqual(result, "mydefault")

    def test_vcap_credentials_used_on_cf(self):
        from backend.core.config import _get_hana_value
        clean_env = {k: v for k, v in os.environ.items() if "HANA" not in k and "DB_" not in k}
        vcap_creds = {"host": "cf-hana-host"}
        with patch.dict(os.environ, clean_env, clear=True), \
             patch("backend.core.config._get_vcap_hana_credentials", return_value=vcap_creds), \
             patch("backend.core.config._is_cloud_foundry_runtime", return_value=True):
            result = _get_hana_value("HANA_HOST", default="")
        self.assertEqual(result, "cf-hana-host")


if __name__ == "__main__":
    unittest.main()
