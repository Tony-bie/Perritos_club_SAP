from __future__ import annotations

from typing import Any


def require_pandas() -> Any:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency 'pandas'. Install it with: pip install -r requirements.txt"
        ) from exc

    return pd


def require_hdbcli() -> Any:
    try:
        from hdbcli import dbapi
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency 'hdbcli'. Install it with: pip install -r requirements.txt"
        ) from exc

    return dbapi


def require_hana_ml() -> Any:
    try:
        import hana_ml
        from hana_ml.algorithms.pal.preprocessing import IsolationForest
        from hana_ml.dataframe import ConnectionContext
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency 'hana-ml'. Install it with: pip install -r requirements.txt"
        ) from exc

    return hana_ml, ConnectionContext, IsolationForest


def parse_bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
