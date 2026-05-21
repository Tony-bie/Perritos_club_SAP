"""
Loads all settings from environment variables into a Settings dataclass.

Also reads .env files locally and VCAP_SERVICES on Cloud Foundry.
Use: from backend.core.config import load_settings; settings = load_settings()
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import requests
except ImportError:
    requests = None


def _get_oauth_token(uaa_url: str, clientid: str, clientsecret: str) -> str:
    if not requests:
        return ""
    try:
        response = requests.post(
            f"{uaa_url}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": clientid,
                "client_secret": clientsecret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("access_token", "")
    except Exception:
        return ""


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
    admin_api_key: str
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
    hana_token: str
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
    # Bloque B: Optimización y retención
    batch_size: int
    retention_days: int
    cleanup_schedule_enabled: bool
    cleanup_schedule_hour: int
    token_bot_telegram: str
    chat_ids: list[int]
    telegram_chatbot_enabled: bool
    llm_enabled: bool
    llm_provider_model: str
    llm_api_key: str
    llm_base_url: str
    llm_temperature: float
    llm_max_tokens: int


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


def _to_int_list(value: str) -> list[int]:
    result: list[int] = []
    for piece in value.split(","):
        cleaned = _clean_str(piece)
        if not cleaned:
            continue
        try:
            result.append(int(cleaned))
        except ValueError:
            continue
    return result


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
    direct = _getenv(*keys, default="")
    if direct:
        return direct

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

        return default

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

    has_hana = bool(_get_hana_value("HANA_HOST", "SAP_HANA_HOST", "DB_HOST", default=""))
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
    db_user = _clean_str(os.getenv("DB_USER"))
    db_password = _clean_str(os.getenv("DB_PASSWORD"))

    return Settings(
        sap_soc_base_url=_getenv("SAP_SOC_BASE_URL", default="").rstrip("/"),
        sap_soc_token=_getenv("SAP_SOC_TOKEN", default=""),
        admin_api_key=_getenv("ADMIN_API_KEY", default=_getenv("SAP_SOC_TOKEN", default="")),
        app_host=_getenv("APP_HOST", default="0.0.0.0"),
        app_port=_to_int(os.getenv("APP_PORT"), 8000),
        enable_worker=_to_bool(_getenv("ENABLE_WORKER", default="true"), True),
        poll_interval_minutes=_resolve_poll_interval_minutes(),
        request_timeout_seconds=_to_int(
            _getenv("REQUEST_TIMEOUT_SECONDS", "SAP_SOC_TIMEOUT_SECONDS", default="30"),
            30,
        ),
        max_retries=_to_int(os.getenv("MAX_RETRIES"), 3),
        retry_backoff_seconds=_to_int(os.getenv("RETRY_BACKOFF_SECONDS"), 2),
        storage_backend=_resolve_storage_backend(),
        sqlite_path=_getenv("SQLITE_PATH", default="./pipeline.db"),
        hana_host=_get_hana_value("HANA_HOST", "SAP_HANA_HOST", "DB_HOST", default=""),
        hana_port=_to_int(_get_hana_value("HANA_PORT", "SAP_HANA_PORT", "DB_PORT", default="443"), 443),
        hana_user=db_user or _get_hana_value("HANA_USER", "SAP_HANA_USER", default=""),
        hana_password=db_password or _get_hana_value("HANA_PASSWORD", "SAP_HANA_PASSWORD", default=""),
        hana_token=_get_hana_value("HANA_TOKEN", default=""),
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
        # Bloque B: Optimización y retención
        batch_size=max(1, _to_int(_getenv("BATCH_SIZE", default="1000"), 1000)),
        retention_days=max(7, _to_int(_getenv("RETENTION_DAYS", default="90"), 90)),
        cleanup_schedule_enabled=_to_bool(_getenv("CLEANUP_SCHEDULE_ENABLED", default="true"), True),
        cleanup_schedule_hour=max(0, min(23, _to_int(_getenv("CLEANUP_SCHEDULE_HOUR", default="2"), 2))),
        token_bot_telegram=_getenv("TOKEN_BOT_TELEGRAM", default=""),
        chat_ids=_to_int_list(_getenv("CHAT_IDS", default="")),
        telegram_chatbot_enabled=_to_bool(_getenv("TELEGRAM_CHATBOT_ENABLED", default="true"), True),
        llm_enabled=_to_bool(_getenv("LLM_ENABLED", default="true"), True),
        llm_provider_model=_getenv("LLM_PROVIDER_MODEL", default=""),
        llm_api_key=_getenv("LLM_API_KEY", default=""),
        llm_base_url=_getenv("LLM_BASE_URL", default=""),
        llm_temperature=_to_float(_getenv("LLM_TEMPERATURE", default="0.2"), 0.2),
        llm_max_tokens=max(100, _to_int(_getenv("LLM_MAX_TOKENS", default="400"), 400)),
    )
