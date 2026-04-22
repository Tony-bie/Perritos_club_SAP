from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from soc_pipeline.domain.models import HanaConfig, RuntimeConfig
from soc_pipeline.shared.runtime import parse_bool_env

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> bool:
        return False


load_dotenv()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest the current SAP SOC 30-minute window, score it, and persist the results."
    )
    subparsers = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--output-dir",
        default=os.getenv("SAP_SOC_OUTPUT_DIR", "data"),
        help="Directory where batches, history, and local state are stored.",
    )
    common.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("SAP_SOC_TIMEOUT_SECONDS", "30")),
        help="HTTP timeout in seconds.",
    )
    common.add_argument(
        "--force",
        action="store_true",
        help="Process the current window even if it was already saved before.",
    )
    common.add_argument(
        "--alert-threshold",
        type=int,
        default=int(os.getenv("SAP_SOC_ALERT_THRESHOLD", "40")),
        help="Threat score threshold used to mark a window as an attack.",
    )
    common.add_argument(
        "--training-min-rows",
        type=int,
        default=int(os.getenv("SAP_SOC_TRAINING_MIN_ROWS", "24")),
        help="Minimum number of stored windows required before training hana-ml models.",
    )
    common.add_argument(
        "--training-contamination",
        type=float,
        default=float(os.getenv("SAP_SOC_TRAINING_CONTAMINATION", "0.1")),
        help="Expected anomaly contamination ratio for hana-ml Isolation Forest.",
    )

    subparsers.add_parser(
        "once",
        parents=[common],
        help="Fetch, score, and save the current window once.",
    )

    poll_parser = subparsers.add_parser(
        "poll",
        parents=[common],
        help="Poll repeatedly and save each new window once.",
    )
    poll_parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("SAP_SOC_POLL_SECONDS", "1800")),
        help="Seconds to wait between polling attempts. Default is one 30-minute SOC window.",
    )

    subparsers.add_parser(
        "train",
        parents=[common],
        help="Train and score a hana-ml Isolation Forest model on stored HANA window metrics.",
    )

    parser.set_defaults(command="once")
    return parser


def load_runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    base_url = os.getenv("SAP_SOC_BASE_URL")
    token = os.getenv("SAP_SOC_TOKEN")

    if not base_url or not token:
        raise ValueError(
            "Missing configuration. Set SAP_SOC_BASE_URL and SAP_SOC_TOKEN in your environment or .env file."
        )

    return RuntimeConfig(
        base_url=base_url,
        token=token,
        timeout_seconds=args.timeout,
        output_dir=Path(args.output_dir),
        alert_threshold=args.alert_threshold,
        poll_interval_seconds=getattr(args, "interval_seconds", int(os.getenv("SAP_SOC_POLL_SECONDS", "1800"))),
        training_min_rows=args.training_min_rows,
        training_contamination=args.training_contamination,
        hana_config=load_hana_config(),
    )


def load_hana_config() -> HanaConfig | None:
    env_credentials = {
        "host": os.getenv("SAP_HANA_HOST"),
        "port": os.getenv("SAP_HANA_PORT"),
        "user": os.getenv("SAP_HANA_USER"),
        "password": os.getenv("SAP_HANA_PASSWORD"),
        "schema": os.getenv("SAP_HANA_SCHEMA"),
    }
    vcap_credentials = load_hana_credentials_from_vcap()
    merged_credentials = merge_hana_credentials(env_credentials, vcap_credentials)

    host = merged_credentials.get("host")
    port = merged_credentials.get("port")
    user = merged_credentials.get("user")
    password = merged_credentials.get("password")

    supplied_values = [host, port, user, password]
    if not any(supplied_values):
        return None

    if not all(supplied_values):
        print(
            "Incomplete SAP HANA configuration detected. The pipeline will continue without HANA until "
            "host, port, user, and password are all available from .env or VCAP_SERVICES.",
            file=sys.stderr,
        )
        return None

    return HanaConfig(
        host=str(host),
        port=int(str(port)),
        user=str(user),
        password=str(password),
        schema=str(merged_credentials.get("schema") or "SOC_PIPELINE"),
        encrypt=parse_bool_env(os.getenv("SAP_HANA_ENCRYPT", "true")),
        validate_certificate=parse_bool_env(os.getenv("SAP_HANA_VALIDATE_CERTIFICATE", "false")),
    )


def merge_hana_credentials(
    primary: dict[str, str | int | None],
    fallback: dict[str, str | int | None] | None,
) -> dict[str, str | int | None]:
    merged = dict(fallback or {})
    for key, value in primary.items():
        if value not in {None, ""}:
            merged[key] = value
    return merged


def load_hana_credentials_from_vcap() -> dict[str, str | int | None] | None:
    raw_vcap = os.getenv("VCAP_SERVICES")
    if not raw_vcap:
        return None

    try:
        services = json.loads(raw_vcap)
    except json.JSONDecodeError:
        return None

    service_name = os.getenv("SAP_HANA_SERVICE_NAME", "").strip()
    matching_instance = find_hana_service_instance(services, preferred_name=service_name or None)
    if matching_instance is None:
        return None

    credentials = matching_instance.get("credentials") or {}
    host = credentials.get("host")
    port = credentials.get("port")
    user = credentials.get("user")
    password = credentials.get("password")

    if not host or not port:
        parsed_host, parsed_port = parse_hana_host_port_from_url(credentials.get("url"))
        host = host or parsed_host
        port = port or parsed_port

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "schema": credentials.get("schema"),
    }


def find_hana_service_instance(
    services: dict[str, list[dict[str, object]]],
    preferred_name: str | None = None,
) -> dict[str, object] | None:
    flattened: list[dict[str, object]] = []
    for service_group in services.values():
        flattened.extend(service_group)

    if preferred_name:
        for instance in flattened:
            if instance.get("name") == preferred_name:
                return instance

    for instance in flattened:
        label = str(instance.get("label") or "").lower()
        tags = [str(tag).lower() for tag in (instance.get("tags") or [])]
        name = str(instance.get("name") or "").lower()
        if "hana" in label or "hana" in name or any("hana" in tag for tag in tags):
            return instance
    return None


def parse_hana_host_port_from_url(url: object) -> tuple[str | None, int | None]:
    if not isinstance(url, str) or not url.strip():
        return None, None

    parsed = urlparse(url)
    return parsed.hostname, parsed.port
