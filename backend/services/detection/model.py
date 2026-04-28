from __future__ import annotations

from typing import Any, Dict, List, Tuple

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

    algorithm = str(settings.model_algorithm or "isolation_forest").strip().lower()

    try:
        import hana_ml
        from hana_ml.dataframe import ConnectionContext
    except ModuleNotFoundError as exc:
        return unavailable_model_signal(f"hana_ml_unavailable:{exc}")

    try:
        with ConnectionContext(
            address=settings.hana_host,
            port=settings.hana_port,
            user=settings.hana_user,
            password=settings.hana_password,
            token=settings.hana_token or None,
            encrypt=settings.hana_encrypt,
            sslValidateCertificate=settings.hana_validate_certificate,
        ) as connection:
            feature_columns = [column.upper() for column in NUMERIC_FEATURE_COLUMNS]
            feature_df = (
                connection.table("WINDOW_FEATURES", schema=settings.hana_schema)
                .select("WINDOW_KEY", *feature_columns)
                .dropna()
            )
            training_row_count = int(feature_df.count())
            if training_row_count < min_training_rows:
                return unavailable_model_signal(f"insufficient_history:{training_row_count}")

            if algorithm in {"kmeans", "k_means", "pal_kmeans"}:
                prediction_rows, model_source = _run_kmeans_scores(
                    feature_df=feature_df,
                    feature_columns=feature_columns,
                    clusters=settings.model_kmeans_clusters,
                    row_count=training_row_count,
                    hana_ml_version=getattr(hana_ml, "__version__", "unknown"),
                )
                score_rows = _prepare_score_rows(prediction_rows, contamination)
            elif algorithm in {"isolation_forest", "iforest"}:
                prediction_rows, model_source = _run_isolation_forest_scores(
                    feature_df=feature_df,
                    feature_columns=feature_columns,
                    hana_ml_version=getattr(hana_ml, "__version__", "unknown"),
                )
                score_rows = _prepare_score_rows(prediction_rows, contamination)
            elif algorithm in {"hybrid", "ensemble", "iforest_kmeans"}:
                iforest_rows, iforest_source = _run_isolation_forest_scores(
                    feature_df=feature_df,
                    feature_columns=feature_columns,
                    hana_ml_version=getattr(hana_ml, "__version__", "unknown"),
                )
                kmeans_rows, kmeans_source = _run_kmeans_scores(
                    feature_df=feature_df,
                    feature_columns=feature_columns,
                    clusters=settings.model_kmeans_clusters,
                    row_count=training_row_count,
                    hana_ml_version=getattr(hana_ml, "__version__", "unknown"),
                )
                iforest_processed = _prepare_score_rows(iforest_rows, contamination)
                kmeans_processed = _prepare_score_rows(kmeans_rows, contamination)
                score_rows = _merge_hybrid_rows(
                    iforest_rows=iforest_processed,
                    kmeans_rows=kmeans_processed,
                    contamination=contamination,
                )
                model_source = f"hana_ml.hybrid({iforest_source}+{kmeans_source})"
            else:
                return unavailable_model_signal(f"unsupported_model_algorithm:{algorithm}")
    except Exception as exc:
        return unavailable_model_signal(f"hana_ml_runtime_error:{exc}")

    if not score_rows:
        return unavailable_model_signal("no_model_scores_returned")

    current_row = next((row for row in score_rows if row["window_key"] == current_window_key), None)
    if current_row is None:
        return unavailable_model_signal("current_window_not_found_in_hana_scores")

    model_signal = {
        "model_available": True,
        "training_row_count": training_row_count,
        "anomaly_score": float(current_row.get("anomaly_score") or 0.0),
        "anomaly_percentile": float(current_row.get("anomaly_percentile") or 0.0),
        "is_anomaly": bool(current_row.get("is_anomaly")),
        "source": model_source,
    }
    component_percentiles = current_row.get("component_percentiles")
    if isinstance(component_percentiles, dict):
        model_signal["component_percentiles"] = component_percentiles

    component_is_anomaly = current_row.get("component_is_anomaly")
    if isinstance(component_is_anomaly, dict):
        model_signal["component_is_anomaly"] = component_is_anomaly

    return model_signal


def _prepare_score_rows(
    prediction_rows: List[Dict[str, Any]],
    contamination: float,
) -> List[Dict[str, Any]]:
    score_rows = [_normalize_prediction_row(row) for row in prediction_rows]
    score_rows = [row for row in score_rows if row["window_key"]]
    if not score_rows:
        return []

    apply_contamination_threshold(score_rows, contamination)
    apply_confidence_scores(score_rows)
    return score_rows


def _merge_hybrid_rows(
    iforest_rows: List[Dict[str, Any]],
    kmeans_rows: List[Dict[str, Any]],
    contamination: float,
) -> List[Dict[str, Any]]:
    if not iforest_rows or not kmeans_rows:
        return []

    iforest_by_key = {str(row["window_key"]): row for row in iforest_rows}
    kmeans_by_key = {str(row["window_key"]): row for row in kmeans_rows}
    shared_keys = [key for key in iforest_by_key.keys() if key in kmeans_by_key]
    if not shared_keys:
        return []

    threshold_percentile = max(0.0, min(100.0, (1.0 - float(contamination)) * 100.0))
    merged_rows: List[Dict[str, Any]] = []

    for key in shared_keys:
        iforest_row = iforest_by_key[key]
        kmeans_row = kmeans_by_key[key]
        iforest_percentile = float(iforest_row.get("anomaly_percentile") or 0.0)
        kmeans_percentile = float(kmeans_row.get("anomaly_percentile") or 0.0)
        hybrid_percentile = (iforest_percentile + kmeans_percentile) / 2.0
        merged_rows.append(
            {
                "window_key": key,
                # Keep this score bounded and comparable across algorithms.
                "anomaly_score": hybrid_percentile,
                "anomaly_percentile": hybrid_percentile,
                "is_anomaly": 1 if hybrid_percentile >= threshold_percentile else 0,
                "component_percentiles": {
                    "isolation_forest": iforest_percentile,
                    "kmeans": kmeans_percentile,
                },
                "component_is_anomaly": {
                    "isolation_forest": bool(iforest_row.get("is_anomaly")),
                    "kmeans": bool(kmeans_row.get("is_anomaly")),
                },
            }
        )

    return merged_rows


def _run_isolation_forest_scores(
    feature_df: Any,
    feature_columns: List[str],
    hana_ml_version: str,
) -> Tuple[List[Dict[str, Any]], str]:
    from hana_ml.algorithms.pal.preprocessing import IsolationForest

    model = IsolationForest(
        random_state=42,
        thread_ratio=0,
    )
    model.fit(
        data=feature_df,
        key="WINDOW_KEY",
        features=feature_columns,
    )
    prediction_df = model.predict(
        data=feature_df,
        key="WINDOW_KEY",
        features=feature_columns,
    )
    prediction_rows = prediction_df.collect().to_dict(orient="records")
    return prediction_rows, f"hana_ml.isolation_forest:{hana_ml_version}"


def _run_kmeans_scores(
    feature_df: Any,
    feature_columns: List[str],
    clusters: int,
    row_count: int,
    hana_ml_version: str,
) -> Tuple[List[Dict[str, Any]], str]:
    from hana_ml.algorithms.pal.clustering import KMeans

    effective_clusters = max(2, min(int(clusters), int(row_count)))

    model = KMeans(
        n_clusters=effective_clusters,
        init="patent",
        max_iter=100,
        thread_ratio=0,
        distance_level="euclidean",
        normalization="min_max",
    )
    prediction_df = model.fit_predict(
        data=feature_df,
        key="WINDOW_KEY",
        features=feature_columns,
    )
    prediction_rows = prediction_df.collect().to_dict(orient="records")
    source = f"hana_ml.kmeans:{hana_ml_version}:k={effective_clusters}"
    return prediction_rows, source


def _normalize_prediction_row(row: Dict[str, Any]) -> Dict[str, Any]:
    upper = {str(key).upper(): value for key, value in row.items()}
    return {
        "window_key": str(upper.get("WINDOW_KEY") or upper.get("ID") or ""),
        "anomaly_score": _first_float(upper, ["DISTANCE", "SCORE", "ANOMALY_SCORE", "RAW_SCORE"]),
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
