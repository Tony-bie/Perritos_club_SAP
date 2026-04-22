from __future__ import annotations

import uuid
from datetime import datetime, timezone

from soc_pipeline.domain.models import RuntimeConfig
from soc_pipeline.infrastructure.hana_ml_service import train_isolation_forest
from soc_pipeline.infrastructure.hana_store import HanaWriter


def run_training(config: RuntimeConfig) -> int:
    if config.hana_config is None:
        raise RuntimeError("Training requires SAP HANA configuration in the environment.")

    started_at = datetime.now(timezone.utc).isoformat()
    run_id = uuid.uuid4().hex
    run_record = {
        "run_id": run_id,
        "algorithm": "hana_ml.algorithms.pal.preprocessing.IsolationForest",
        "feature_table": "WINDOW_METRICS",
        "training_row_count": 0,
        "contamination": config.training_contamination,
        "status": "RUNNING",
        "details": {},
        "started_at_utc": started_at,
        "completed_at_utc": None,
    }

    with HanaWriter(config.hana_config) as hana_writer:
        hana_writer.upsert_model_run(run_record)
        try:
            result = train_isolation_forest(
                hana_config=config.hana_config,
                min_rows=config.training_min_rows,
                contamination=config.training_contamination,
            )
            run_record.update(
                {
                    "training_row_count": result["training_row_count"],
                    "status": "COMPLETED",
                    "details": result["summary"],
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            hana_writer.upsert_model_scores(run_id, result["score_rows"])
            hana_writer.upsert_model_run(run_record)
        except Exception as exc:
            run_record.update(
                {
                    "status": "FAILED",
                    "details": {"error": str(exc)},
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            hana_writer.upsert_model_run(run_record)
            raise

    print(f"Training run: {run_id}")
    print(f"Training rows: {run_record['training_row_count']}")
    print(f"Status: {run_record['status']}")
    print(f"Stored scores: {run_record['details'].get('score_row_count', 0)}")
    print(f"Detected anomalies: {run_record['details'].get('anomaly_count', 0)}")
    return 0
