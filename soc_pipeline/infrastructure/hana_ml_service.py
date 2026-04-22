from __future__ import annotations

from typing import Any

from soc_pipeline.domain.models import HanaConfig
from soc_pipeline.shared.runtime import require_hana_ml, require_pandas

WINDOW_FEATURE_COLUMNS = [
    "TOTAL_RECORDS",
    "SYSTEM_LOG_COUNT",
    "LLM_LOG_COUNT",
    "ERROR_COUNT",
    "SECURITY_COUNT",
    "WARNING_COUNT",
    "AUDIT_COUNT",
    "DEBUG_COUNT",
    "PERF_COUNT",
    "HTTP_4XX_COUNT",
    "HTTP_5XX_COUNT",
    "HTTP_4XX_RATE",
    "HTTP_5XX_RATE",
    "UNIQUE_CLIENT_IPS",
    "UNIQUE_SERVICES",
    "UNIQUE_IP_SERVICE_PAIRS",
    "MAX_EVENTS_FROM_SINGLE_IP",
    "MAX_SERVICES_FROM_SINGLE_IP",
    "SUSPICIOUS_IP_COUNT",
    "AVG_EVENTS_PER_IP",
    "AVG_EVENTS_PER_SERVICE",
    "TOP_IP_EVENT_SHARE",
    "TOP_SERVICE_EVENT_SHARE",
    "SUSPICIOUS_IP_RATIO",
    "IP_BURST_RATIO",
    "PAIR_REUSE_RATIO",
    "CLIENT_IP_ENTROPY",
    "SERVICE_ENTROPY",
    "LLM_REQUEST_COUNT",
    "LLM_TIMEOUT_COUNT",
    "LLM_ERROR_COUNT",
    "LLM_COST_PER_REQUEST",
    "LLM_MODEL_ENTROPY",
    "AVG_LLM_LATENCY_MS",
    "P95_LLM_LATENCY_MS",
    "TOTAL_LLM_COST_USD",
    "SYSTEM_ERROR_RATE",
    "LLM_TIMEOUT_RATE",
    "LLM_ERROR_RATE",
    "LLM_TIMEOUT_PLUS_ERROR_RATE",
    "SECURITY_ERROR_RATIO",
    "DELTA_TOTAL_RECORDS",
    "DELTA_ERROR_COUNT",
    "DELTA_SECURITY_COUNT",
    "DELTA_UNIQUE_CLIENT_IPS",
    "DELTA_UNIQUE_SERVICES",
    "DELTA_AVG_LLM_LATENCY_MS",
    "DELTA_P95_LLM_LATENCY_MS",
    "DELTA_TOTAL_LLM_COST_USD",
    "DELTA_TOP_IP_EVENT_SHARE",
    "DELTA_LLM_TIMEOUT_PLUS_ERROR_RATE",
    "THREAT_SCORE",
    "DETECTION_COUNT",
]


def train_isolation_forest(
    hana_config: HanaConfig,
    min_rows: int,
    contamination: float,
) -> dict[str, Any]:
    result = fit_predict_isolation_forest(
        hana_config=hana_config,
        min_rows=min_rows,
        contamination=contamination,
    )
    anomaly_count = sum(1 for row in result["score_rows"] if row["is_anomaly"] == 1)
    return {
        "algorithm": "hana_ml.algorithms.pal.preprocessing.IsolationForest",
        "feature_table": "WINDOW_METRICS",
        "training_row_count": result["training_row_count"],
        "contamination": contamination,
        "score_rows": result["score_rows"],
        "summary": {
            "score_row_count": len(result["score_rows"]),
            "anomaly_count": anomaly_count,
            "hana_ml_version": result["hana_ml_version"],
            "feature_columns": WINDOW_FEATURE_COLUMNS,
        },
    }


def score_current_window(
    hana_config: HanaConfig,
    window_key: str,
    min_rows: int,
    contamination: float,
) -> dict[str, Any]:
    result = fit_predict_isolation_forest(
        hana_config=hana_config,
        min_rows=min_rows,
        contamination=contamination,
    )
    current_row = next((row for row in result["score_rows"] if row["window_key"] == window_key), None)
    if current_row is None:
        raise RuntimeError(f"Current window {window_key} was not found in HANA model scores.")

    return {
        "model_available": True,
        "training_row_count": result["training_row_count"],
        "anomaly_score": float(current_row["anomaly_score"] or 0.0),
        "confidence_score": float(current_row["confidence_score"] or 0.0),
        "is_anomaly": bool(current_row["is_anomaly"]),
        "source": "hana_ml.isolation_forest",
    }


def fit_predict_isolation_forest(
    hana_config: HanaConfig,
    min_rows: int,
    contamination: float,
) -> dict[str, Any]:
    hana_ml, ConnectionContext, IsolationForest = require_hana_ml()

    with ConnectionContext(
        address=hana_config.host,
        port=hana_config.port,
        user=hana_config.user,
        password=hana_config.password,
        encrypt=hana_config.encrypt,
        sslValidateCertificate=hana_config.validate_certificate,
    ) as cc:
        metrics_df = (
            cc.table("WINDOW_METRICS", schema=hana_config.schema)
            .select("WINDOW_KEY", *WINDOW_FEATURE_COLUMNS)
            .dropna()
        )
        training_row_count = int(metrics_df.count())
        if training_row_count < min_rows:
            raise RuntimeError(
                f"Not enough HANA training rows yet. Need at least {min_rows}, found {training_row_count}."
            )

        model = IsolationForest(
            random_state=42,
            thread_ratio=0,
        )
        model.fit(
            data=metrics_df,
            key="WINDOW_KEY",
            features=WINDOW_FEATURE_COLUMNS,
        )
        prediction_df = model.predict(
            data=metrics_df,
            key="WINDOW_KEY",
            features=WINDOW_FEATURE_COLUMNS,
        )
        prediction_pdf = prediction_df.collect()

    score_rows = []
    for row in prediction_pdf.to_dict(orient="records"):
        normalized = normalize_prediction_row(row)
        score_rows.append(
            {
                "window_key": normalized["window_key"],
                "anomaly_score": normalized["anomaly_score"],
                "is_anomaly": normalized["is_anomaly"],
                "raw": row,
            }
        )

    apply_contamination_threshold(score_rows, contamination)
    apply_confidence_scores(score_rows)
    return {
        "training_row_count": training_row_count,
        "score_rows": score_rows,
        "hana_ml_version": getattr(hana_ml, "__version__", "unknown"),
    }


def normalize_prediction_row(row: dict[str, Any]) -> dict[str, Any]:
    upper = {str(key).upper(): value for key, value in row.items()}
    window_key = upper.get("WINDOW_KEY") or upper.get("ID")
    anomaly_score = first_numeric(upper, ["SCORE", "ANOMALY_SCORE", "RAW_SCORE"])
    is_anomaly = first_int_flag(upper, ["IS_ANOMALY", "OUTLIER", "PREDICTION", "LABEL"])

    return {
        "window_key": str(window_key),
        "anomaly_score": anomaly_score,
        "is_anomaly": is_anomaly,
    }


def first_numeric(row: dict[str, Any], preferred_keys: list[str]) -> float | None:
    for key in preferred_keys:
        value = row.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def first_int_flag(row: dict[str, Any], preferred_keys: list[str]) -> int | None:
    for key in preferred_keys:
        value = row.get(key)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def apply_contamination_threshold(score_rows: list[dict[str, Any]], contamination: float) -> None:
    unresolved = [row for row in score_rows if row["is_anomaly"] is None and row["anomaly_score"] is not None]
    if not unresolved:
        return

    pd = require_pandas()
    scores = pd.Series([row["anomaly_score"] for row in unresolved])
    threshold = float(scores.quantile(max(0.0, min(1.0, 1.0 - contamination))))

    for row in unresolved:
        row["is_anomaly"] = 1 if float(row["anomaly_score"]) >= threshold else 0


def apply_confidence_scores(score_rows: list[dict[str, Any]]) -> None:
    scored_rows = [row for row in score_rows if row["anomaly_score"] is not None]
    if not scored_rows:
        return

    pd = require_pandas()
    score_frame = pd.DataFrame(scored_rows)
    score_frame["confidence_score"] = score_frame["anomaly_score"].rank(pct=True, method="average") * 100.0
    confidence_by_window = {
        str(row["window_key"]): float(row["confidence_score"])
        for row in score_frame.to_dict(orient="records")
    }
    for row in score_rows:
        row["confidence_score"] = confidence_by_window.get(str(row["window_key"]), 0.0)
