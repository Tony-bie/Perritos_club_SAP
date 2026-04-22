import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # Running without python-dotenv is allowed if env vars are already exported.
    pass


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
    error_security_threshold: int


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    return Settings(
        sap_soc_base_url=os.getenv("SAP_SOC_BASE_URL", "").rstrip("/"),
        sap_soc_token=os.getenv("SAP_SOC_TOKEN", ""),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        enable_worker=_to_bool(os.getenv("ENABLE_WORKER", "false"), False),
        poll_interval_minutes=int(os.getenv("POLL_INTERVAL_MINUTES", "30")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        retry_backoff_seconds=int(os.getenv("RETRY_BACKOFF_SECONDS", "2")),
        storage_backend=os.getenv("STORAGE_BACKEND", "sqlite").strip().lower(),
        sqlite_path=os.getenv("SQLITE_PATH", "./pipeline.db"),
        hana_host=os.getenv("HANA_HOST", ""),
        hana_port=int(os.getenv("HANA_PORT", "443")),
        hana_user=os.getenv("HANA_USER", ""),
        hana_password=os.getenv("HANA_PASSWORD", ""),
        hana_schema=os.getenv("HANA_SCHEMA", "SOC_PIPELINE"),
        error_security_threshold=int(os.getenv("ERROR_SECURITY_THRESHOLD", "25")),
    )
