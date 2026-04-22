from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soc_pipeline.domain.models import UtcWindow
from soc_pipeline.shared.runtime import require_pandas


def load_state(output_dir: Path) -> dict[str, Any]:
    state_path = output_dir / "ingestion_state.json"
    if not state_path.exists():
        return {}

    with state_path.open("r", encoding="utf-8") as state_file:
        return json.load(state_file)


def save_state(output_dir: Path, state: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "ingestion_state.json"
    with state_path.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2)


def load_metrics_history(output_dir: Path) -> Any:
    pd = require_pandas()
    history_path = output_dir / "window_metrics_history.csv"
    if not history_path.exists():
        return pd.DataFrame()

    return pd.read_csv(history_path)


def save_metrics_history(output_dir: Path, metrics: dict[str, Any]) -> None:
    pd = require_pandas()
    history_path = output_dir / "window_metrics_history.csv"
    output_dir.mkdir(parents=True, exist_ok=True)

    row = pd.DataFrame([metrics])
    if history_path.exists():
        history_df = pd.read_csv(history_path)
        history_df = history_df[history_df["window_key"] != metrics["window_key"]]
        history_df = pd.concat([history_df, row], ignore_index=True)
    else:
        history_df = row

    history_df = history_df.sort_values(by="window_start_utc").reset_index(drop=True)
    history_df.to_csv(history_path, index=False)


def persist_batch(
    output_dir: Path,
    window: UtcWindow,
    raw_records: list[dict[str, Any]],
    normalized_df: Any,
    info_payload: dict[str, Any],
    api_total_pages: int,
    window_metrics: dict[str, Any],
    ip_features: Any,
    llm_features: Any,
    detections: list[dict[str, Any]],
) -> dict[str, Path]:
    batch_dir = output_dir / "batches" / window.key
    batch_dir.mkdir(parents=True, exist_ok=True)

    raw_path = batch_dir / "raw.json"
    normalized_path = batch_dir / "normalized.csv"
    summary_path = batch_dir / "summary.json"
    metrics_path = batch_dir / "window_metrics.json"
    detections_path = batch_dir / "detections.json"
    ip_features_path = batch_dir / "ip_features.csv"
    llm_features_path = batch_dir / "llm_features.csv"

    with raw_path.open("w", encoding="utf-8") as raw_file:
        json.dump(raw_records, raw_file, indent=2, ensure_ascii=True)

    normalized_df.to_csv(normalized_path, index=False)
    ip_features.to_csv(ip_features_path, index=False)
    llm_features.to_csv(llm_features_path, index=False)

    with metrics_path.open("w", encoding="utf-8") as metrics_file:
        json.dump(window_metrics, metrics_file, indent=2, ensure_ascii=True)

    with detections_path.open("w", encoding="utf-8") as detections_file:
        json.dump(detections, detections_file, indent=2, ensure_ascii=True)

    summary = {
        "window_key": window.key,
        "window_start_utc": window.start.isoformat(),
        "window_end_utc": window.end.isoformat(),
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_record_count": len(raw_records),
        "normalized_record_count": int(len(normalized_df)),
        "api_total_pages": api_total_pages,
        "api_info": info_payload,
        "window_metrics": window_metrics,
        "detection_count": len(detections),
        "attack_predicted": window_metrics["attack_predicted"],
        "top_detection_rules": [detection["rule_name"] for detection in detections[:5]],
    }

    with summary_path.open("w", encoding="utf-8") as summary_file:
        json.dump(summary, summary_file, indent=2, ensure_ascii=True)

    return {
        "batch_dir": batch_dir,
        "raw_path": raw_path,
        "normalized_path": normalized_path,
        "summary_path": summary_path,
        "metrics_path": metrics_path,
        "detections_path": detections_path,
        "ip_features_path": ip_features_path,
        "llm_features_path": llm_features_path,
    }
