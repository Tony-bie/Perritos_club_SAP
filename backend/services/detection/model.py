from __future__ import annotations

from typing import Any, Dict, List

from backend.core.config import Settings
from backend.services.ingestion.features import NUMERIC_FEATURE_COLUMNS


def unavailable_model_signal(source: str) -> Dict[str, Any]:
    return {
        "model_available": False,
        "training_row_count": 0,
        "anomaly_score": 0.0,
        "anomaly_percentile": 0.0,
        "is_anomaly": False,
        "source": source,
    }


def score_window_metrics(
    settings: Settings,
    current_window_key: str,
    min_training_rows: int,
    contamination: float,
) -> Dict[str, Any]:
    if settings.storage_backend != "hana":
        return unavailable_model_signal("hana_ml_requires_hana_backend")

    try:
        import hana_ml
        from hana_ml.algorithms.pal.preprocessing import IsolationForest
        from hana_ml.dataframe import ConnectionContext
    except ModuleNotFoundError as exc:
        return unavailable_model_signal(f"hana_ml_unavailable:{exc}")

    try:
        with ConnectionContext(
            address=settings.hana_host,
            port=settings.hana_port,
            user=settings.hana_user,
            password=settings.hana_password,
            encrypt=settings.hana_encrypt,
            sslValidateCertificate=settings.hana_validate_certificate,
        ) as connection:
            feature_df = (
                connection.table("WINDOW_FEATURES", schema=settings.hana_schema)
                .select("WINDOW_KEY", *[column.upper() for column in NUMERIC_FEATURE_COLUMNS])
                .dropna()
            )
            training_row_count = int(feature_df.count())
            if training_row_count < min_training_rows:
                return unavailable_model_signal(f"insufficient_history:{training_row_count}")

            model = IsolationForest(
                random_state=42,
                thread_ratio=0,
            )
            model.fit(
                data=feature_df,
                key="WINDOW_KEY",
                features=[column.upper() for column in NUMERIC_FEATURE_COLUMNS],
            )
            prediction_df = model.predict(
                data=feature_df,
                key="WINDOW_KEY",
                features=[column.upper() for column in NUMERIC_FEATURE_COLUMNS],
            )
            prediction_rows = prediction_df.collect().to_dict(orient="records")
    except Exception as exc:
        return unavailable_model_signal(f"hana_ml_runtime_error:{exc}")

    score_rows = [_normalize_prediction_row(row) for row in prediction_rows]
    apply_contamination_threshold(score_rows, contamination)
    apply_confidence_scores(score_rows)

    current_row = next((row for row in score_rows if row["window_key"] == current_window_key), None)
    if current_row is None:
        return unavailable_model_signal("current_window_not_found_in_hana_scores")

    return {
        "model_available": True,
        "training_row_count": training_row_count,
        "anomaly_score": float(current_row.get("anomaly_score") or 0.0),
        "anomaly_percentile": float(current_row.get("anomaly_percentile") or 0.0),
        "is_anomaly": bool(current_row.get("is_anomaly")),
        "source": f"hana_ml.isolation_forest:{getattr(hana_ml, '__version__', 'unknown')}",
    }


def _normalize_prediction_row(row: Dict[str, Any]) -> Dict[str, Any]:
    upper = {str(key).upper(): value for key, value in row.items()}
    return {
        "window_key": str(upper.get("WINDOW_KEY") or upper.get("ID") or ""),
        "anomaly_score": _first_float(upper, ["SCORE", "ANOMALY_SCORE", "RAW_SCORE"]),
        "is_anomaly": _first_int(upper, ["IS_ANOMALY", "OUTLIER", "PREDICTION", "LABEL"]),
    }


def _first_float(row: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        value = row.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_int(row: Dict[str, Any], keys: List[str]) -> int | None:
    for key in keys:
        value = row.get(key)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def apply_contamination_threshold(score_rows: List[Dict[str, Any]], contamination: float) -> None:
    unresolved = [row for row in score_rows if row["is_anomaly"] is None and row["anomaly_score"] is not None]
    if not unresolved:
        return

    scores = sorted(float(row["anomaly_score"]) for row in unresolved)
    if not scores:
        return

    cutoff_index = max(0, min(len(scores) - 1, int(round((1.0 - contamination) * (len(scores) - 1)))))
    threshold = scores[cutoff_index]
    for row in unresolved:
        row["is_anomaly"] = 1 if float(row["anomaly_score"]) >= threshold else 0


def apply_confidence_scores(score_rows: List[Dict[str, Any]]) -> None:
    scored = [row for row in score_rows if row["anomaly_score"] is not None]
    if not scored:
        return

    ordered = sorted(scored, key=lambda row: float(row["anomaly_score"]))
    total = len(ordered)
    for index, row in enumerate(ordered, start=1):
        row["anomaly_percentile"] = (index / total) * 100.0
