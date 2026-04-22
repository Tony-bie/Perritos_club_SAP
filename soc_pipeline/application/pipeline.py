from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from typing import Any

from soc_pipeline.application.detection import default_ml_signal, detect_threats
from soc_pipeline.application.features import (
    build_ip_features,
    build_llm_features,
    build_window_metrics,
    current_utc_window,
    normalize_records,
)
from soc_pipeline.domain.models import RuntimeConfig, UtcWindow
from soc_pipeline.infrastructure.hana_ml_service import score_current_window
from soc_pipeline.infrastructure.hana_store import HanaWriter
from soc_pipeline.infrastructure.local_store import (
    load_metrics_history,
    load_state,
    persist_batch,
    save_metrics_history,
    save_state,
)
from soc_pipeline.infrastructure.sap_api import SapSocClient


def ingest_current_window(client: SapSocClient, config: RuntimeConfig, force: bool = False) -> bool:
    window = current_utc_window()
    state = load_state(config.output_dir)

    if state.get("last_window_key") == window.key and not force:
        print(f"Skipping window {window.label} because it is already stored locally.")
        return False

    raw_records, info_payload, api_total_pages = client.get_all_logs()
    normalized_df = normalize_records(raw_records)
    history_df = load_metrics_history(config.output_dir)
    ip_features = build_ip_features(normalized_df, window)
    llm_features = build_llm_features(normalized_df, window)
    window_metrics = build_window_metrics(normalized_df, window, ip_features, history_df)

    ml_signal = default_ml_signal()
    hana_available = False
    if config.hana_config is not None:
        hana_available, ml_signal = try_hana_window_sync(
            config=config,
            raw_records=raw_records,
            window=window,
            window_metrics=window_metrics,
        )

    detections, detection_summary = detect_threats(
        window_metrics,
        alert_threshold=config.alert_threshold,
        ml_signal=ml_signal,
    )
    window_metrics.update(detection_summary)

    paths = persist_batch(
        output_dir=config.output_dir,
        window=window,
        raw_records=raw_records,
        normalized_df=normalized_df,
        info_payload=info_payload,
        api_total_pages=api_total_pages,
        window_metrics=window_metrics,
        ip_features=ip_features,
        llm_features=llm_features,
        detections=detections,
    )
    save_metrics_history(config.output_dir, window_metrics)

    if hana_available:
        try_hana_detection_sync(config=config, window_metrics=window_metrics, detections=detections)

    state.update(
        {
            "last_window_key": window.key,
            "last_saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "last_batch_dir": str(paths["batch_dir"]),
            "last_record_count": int(len(normalized_df)),
            "last_threat_score": int(window_metrics["threat_score"]),
            "last_attack_predicted": bool(window_metrics["attack_predicted"]),
        }
    )
    save_state(config.output_dir, state)

    print(f"Saved window {window.label}")
    print(f"Records: {len(normalized_df)}")
    print(f"Pages: {api_total_pages}")
    print(f"Threat score: {window_metrics['threat_score']} / 100")
    print(f"Attack predicted: {window_metrics['attack_predicted']}")
    print(f"Detections: {window_metrics['detection_count']}")
    print(f"Batch folder: {paths['batch_dir']}")
    if detections:
        print("Triggered rules:")
        for detection in detections[:5]:
            print(f"- {detection['rule_name']} [{detection['severity']}]")
    return True


def try_hana_window_sync(
    config: RuntimeConfig,
    raw_records: list[dict[str, Any]],
    window: UtcWindow,
    window_metrics: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    if config.hana_config is None:
        return False, default_ml_signal()

    try:
        with HanaWriter(config.hana_config) as hana_writer:
            hana_writer.upsert_raw_logs(raw_records, window)
            hana_writer.upsert_window_metrics(window_metrics, saved_at_utc=datetime.now(timezone.utc).isoformat())
        try:
            ml_signal = score_current_window(
                hana_config=config.hana_config,
                window_key=window.key,
                min_rows=config.training_min_rows,
                contamination=config.training_contamination,
            )
        except Exception as exc:
            ml_signal = {
                **default_ml_signal(),
                "source": f"ml_unavailable:{exc}",
            }
        return True, ml_signal
    except Exception as exc:
        print(f"HANA sync unavailable for window {window.key}: {exc}", file=sys.stderr)
        return False, {
            **default_ml_signal(),
            "source": f"hana_unavailable:{exc}",
        }


def try_hana_detection_sync(
    config: RuntimeConfig,
    window_metrics: dict[str, Any],
    detections: list[dict[str, Any]],
) -> bool:
    if config.hana_config is None:
        return False

    try:
        with HanaWriter(config.hana_config) as hana_writer:
            hana_writer.upsert_window_metrics(window_metrics, saved_at_utc=datetime.now(timezone.utc).isoformat())
            hana_writer.upsert_detections(detections)
        return True
    except Exception as exc:
        print(
            f"HANA detection persistence unavailable for window {window_metrics.get('window_key')}: {exc}",
            file=sys.stderr,
        )
        return False


def run_once(config: RuntimeConfig, force: bool = False) -> int:
    client = SapSocClient(
        base_url=config.base_url,
        token=config.token,
        timeout_seconds=config.timeout_seconds,
    )
    ingest_current_window(client=client, config=config, force=force)
    return 0


def run_poll(config: RuntimeConfig, force: bool = False) -> int:
    client = SapSocClient(
        base_url=config.base_url,
        token=config.token,
        timeout_seconds=config.timeout_seconds,
    )

    while True:
        try:
            processed = ingest_current_window(client=client, config=config, force=force)
            if not processed:
                print("No new window yet. Waiting for the next polling cycle.")
        except KeyboardInterrupt:
            print("Polling stopped by user.")
            return 0
        except Exception as exc:
            print(f"Ingestion failed: {exc}", file=sys.stderr)

        time.sleep(config.poll_interval_seconds)
