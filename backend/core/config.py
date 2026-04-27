import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _is_cloud_foundry_runtime() -> bool:
    return bool(os.getenv("VCAP_APPLICATION"))


def _load_local_env_fallback() -> None:
    if _is_cloud_foundry_runtime():
        return

    env_path = Path(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


try:
    from dotenv import load_dotenv

    # In Cloud Foundry, prefer process env / VCAP_* and avoid loading local .env files.
    if not _is_cloud_foundry_runtime():
        load_dotenv()
except Exception:
    # Running without python-dotenv is allowed if env vars are already exported.
    _load_local_env_fallback()


@dataclass
class Settings:
    sap_soc_base_url: str
    sap_soc_token: str
    app_host: str
    app_port: int
    enable_worker: bool
    poll_interval_minutes: int
    request_timeout_seconds: int
    max_retries: int
    retry_backoff_seconds: int
    storage_backend: str
    sqlite_path: str
    hana_host: str
    hana_port: int
    hana_user: str
    hana_password: str
    hana_schema: str
    hana_encrypt: bool
    hana_validate_certificate: bool
    error_security_threshold: int
    attack_score_threshold: int
    model_enabled: bool
    model_algorithm: str
    model_min_training_rows: int
    model_contamination: float
    model_kmeans_clusters: int
    model_history_limit: int


def _clean_str(value: str | None, default: str = "") -> str:
    if value is None:
        return default
    return value.strip().strip('"').strip("'")


def _getenv(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        cleaned = _clean_str(raw)
        if cleaned != "":
            return cleaned
    return default


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str | None, default: int) -> int:
    try:
        return int(_clean_str(value, str(default)))
    except (TypeError, ValueError):
        return default


def _to_float(value: str | None, default: float) -> float:
    try:
        return float(_clean_str(value, str(default)))
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def _get_vcap_hana_credentials() -> dict[str, str]:
    raw_services = os.getenv("VCAP_SERVICES")
    if not raw_services:
        return {}

    try:
        services = json.loads(raw_services)
    except json.JSONDecodeError:
        return {}

    hana_services = services.get("hana-cloud") or []
    if not hana_services:
        return {}

    first_service = hana_services[0] or {}
    credentials = first_service.get("credentials") or {}
    if not isinstance(credentials, dict):
        return {}

    parsed: dict[str, str] = {}

    for source_key, target_key in (
        ("host", "host"),
        ("hostname", "host"),
        ("port", "port"),
        ("user", "user"),
        ("username", "user"),
        ("password", "password"),
        ("schema", "schema"),
    ):
        value = credentials.get(source_key)
        if value is not None:
            cleaned = _clean_str(str(value))
            if cleaned:
                parsed[target_key] = cleaned

    jdbc_url = credentials.get("url")
    if isinstance(jdbc_url, str) and jdbc_url:
        normalized_url = jdbc_url.replace("jdbc:sap://", "https://", 1)
        parsed_url = urlparse(normalized_url)
        if parsed_url.hostname and "host" not in parsed:
            parsed["host"] = parsed_url.hostname
        if parsed_url.port and "port" not in parsed:
            parsed["port"] = str(parsed_url.port)

        query_params = parse_qs(parsed_url.query)
        encrypt = query_params.get("encrypt", [None])[0]
        validate_certificate = query_params.get("validateCertificate", [None])[0]
        if encrypt is not None:
            parsed["encrypt"] = _clean_str(str(encrypt))
        if validate_certificate is not None:
            parsed["validate_certificate"] = _clean_str(str(validate_certificate))

    return parsed


def _get_hana_value(*keys: str, default: str = "") -> str:
    credentials = _get_vcap_hana_credentials()

    # In Cloud Foundry, service binding credentials should win over manually set
    # HANA_* variables so credential rotations don't break deployments.
    prefer_vcap = _is_cloud_foundry_runtime() and bool(credentials)

    if prefer_vcap:
        for key in keys:
            normalized = key.lower()
            if normalized.startswith("sap_"):
                normalized = normalized[4:]
            if normalized.startswith("hana_"):
                normalized = normalized[5:]
            value = credentials.get(normalized)
            if value:
                return value

        direct = _getenv(*keys, default="")
        if direct:
            return direct
        return default

    direct = _getenv(*keys, default="")
    if direct:
        return direct

    for key in keys:
        normalized = key.lower()
        if normalized.startswith("sap_"):
            normalized = normalized[4:]
        if normalized.startswith("hana_"):
            normalized = normalized[5:]
        value = credentials.get(normalized)
        if value:
            return value
    return default


def _resolve_storage_backend() -> str:
    configured = _getenv("STORAGE_BACKEND", default="").lower()
    if configured:
        return configured

    has_hana = bool(_get_hana_value("HANA_HOST", "SAP_HANA_HOST", default=""))
    return "hana" if has_hana else "sqlite"


def _resolve_poll_interval_minutes() -> int:
    configured_minutes = _getenv("POLL_INTERVAL_MINUTES", default="")
    if configured_minutes:
        return max(1, _to_int(configured_minutes, 30))

    legacy_seconds = _getenv("SAP_SOC_POLL_SECONDS", default="")
    if legacy_seconds:
        seconds = max(60, _to_int(legacy_seconds, 1800))
        return max(1, (seconds + 59) // 60)

    return 30


def load_settings() -> Settings:
    return Settings(
        sap_soc_base_url=_getenv("SAP_SOC_BASE_URL", default="").rstrip("/"),
        sap_soc_token=_getenv("SAP_SOC_TOKEN", default=""),
        app_host=_getenv("APP_HOST", default="0.0.0.0"),
        app_port=_to_int(os.getenv("APP_PORT"), 8000),
        enable_worker=_to_bool(_getenv("ENABLE_WORKER", default="false"), False),
        poll_interval_minutes=_resolve_poll_interval_minutes(),
        request_timeout_seconds=_to_int(
            _getenv("REQUEST_TIMEOUT_SECONDS", "SAP_SOC_TIMEOUT_SECONDS", default="30"),
            30,
        ),
        max_retries=_to_int(os.getenv("MAX_RETRIES"), 3),
        retry_backoff_seconds=_to_int(os.getenv("RETRY_BACKOFF_SECONDS"), 2),
        storage_backend=_resolve_storage_backend(),
        sqlite_path=_getenv("SQLITE_PATH", default="./pipeline.db"),
        hana_host=_get_hana_value("HANA_HOST", "SAP_HANA_HOST", default=""),
        hana_port=_to_int(_get_hana_value("HANA_PORT", "SAP_HANA_PORT", default="443"), 443),
        hana_user=_get_hana_value("HANA_USER", "SAP_HANA_USER", default=""),
        hana_password=_get_hana_value("HANA_PASSWORD", "SAP_HANA_PASSWORD", default=""),
        hana_schema=_get_hana_value("HANA_SCHEMA", "SAP_HANA_SCHEMA", default="SOC_PIPELINE"),
        hana_encrypt=_to_bool(_get_hana_value("HANA_ENCRYPT", "SAP_HANA_ENCRYPT", default="true"), True),
        hana_validate_certificate=_to_bool(
            _get_hana_value(
                "HANA_VALIDATE_CERTIFICATE",
                "SAP_HANA_VALIDATE_CERTIFICATE",
                default="false",
            ),
            False,
        ),
        error_security_threshold=_to_int(
            _getenv("ERROR_SECURITY_THRESHOLD", "SAP_SOC_ALERT_THRESHOLD", default="25"),
            25,
        ),
        attack_score_threshold=_to_int(
            _getenv("ATTACK_SCORE_THRESHOLD", default="70"),
            70,
        ),
        model_enabled=_to_bool(_getenv("MODEL_ENABLED", default="true"), True),
        model_algorithm=_getenv("MODEL_ALGORITHM", default="isolation_forest").lower(),
        model_min_training_rows=_to_int(_getenv("MODEL_MIN_TRAINING_ROWS", default="30"), 30),
        model_contamination=_to_float(_getenv("MODEL_CONTAMINATION", default="0.15"), 0.15),
        model_kmeans_clusters=max(2, _to_int(_getenv("MODEL_KMEANS_CLUSTERS", default="4"), 4)),
        model_history_limit=_to_int(_getenv("MODEL_HISTORY_LIMIT", default="200"), 200),
    )
