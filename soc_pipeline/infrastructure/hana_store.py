from __future__ import annotations

import json
import uuid
from typing import Any

from soc_pipeline.domain.constants import LLM_LOG_TYPES
from soc_pipeline.domain.models import HanaConfig, UtcWindow
from soc_pipeline.shared.runtime import require_hdbcli, safe_float, safe_int, safe_str


class HanaWriter:
    def __init__(self, config: HanaConfig) -> None:
        self.config = config
        self.connection: Any | None = None

    def __enter__(self) -> "HanaWriter":
        self.connect()
        self.ensure_schema()
        self.ensure_tables()
        return self

    def __exit__(self, exc_type: Any, exc: Any, exc_tb: Any) -> None:
        if self.connection is not None:
            self.connection.close()

    def connect(self) -> None:
        dbapi = require_hdbcli()
        self.connection = dbapi.connect(
            address=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            encrypt=self.config.encrypt,
            sslValidateCertificate=self.config.validate_certificate,
        )

    def ensure_schema(self) -> None:
        self._execute_ddl(f'CREATE SCHEMA "{self.config.schema}"')

    def ensure_tables(self) -> None:
        schema = self.config.schema
        table_statements = [
            f'''
            CREATE COLUMN TABLE "{schema}"."RAW_LOGS" (
                "LOG_ID" NVARCHAR(255) PRIMARY KEY,
                "WINDOW_KEY" NVARCHAR(64) NOT NULL,
                "WINDOW_START_UTC" NVARCHAR(40),
                "WINDOW_END_UTC" NVARCHAR(40),
                "LOG_TIMESTAMP_UTC" NVARCHAR(80),
                "SAP_FUNCTION_LOG_TYPE" NVARCHAR(80),
                "IS_LLM_LOG" SMALLINT,
                "IS_SYSTEM_LOG" SMALLINT,
                "CLIENT_IP" NVARCHAR(128),
                "SERVICE_ID" NVARCHAR(255),
                "HTTP_STATUS_CODE" INTEGER,
                "LLM_MODEL_ID" NVARCHAR(255),
                "LLM_STATUS" NVARCHAR(80),
                "LLM_COST_USD" DOUBLE,
                "LLM_RESPONSE_TIME_MS" DOUBLE,
                "RAW_PAYLOAD_JSON" NCLOB
            )
            ''',
            f'''
            CREATE COLUMN TABLE "{schema}"."WINDOW_METRICS" (
                "WINDOW_KEY" NVARCHAR(64) PRIMARY KEY,
                "WINDOW_START_UTC" NVARCHAR(40),
                "WINDOW_END_UTC" NVARCHAR(40),
                "TOTAL_RECORDS" INTEGER,
                "SYSTEM_LOG_COUNT" INTEGER,
                "LLM_LOG_COUNT" INTEGER,
                "ERROR_COUNT" INTEGER,
                "SECURITY_COUNT" INTEGER,
                "WARNING_COUNT" INTEGER,
                "AUDIT_COUNT" INTEGER,
                "DEBUG_COUNT" INTEGER,
                "PERF_COUNT" INTEGER,
                "HTTP_4XX_COUNT" INTEGER,
                "HTTP_5XX_COUNT" INTEGER,
                "HTTP_4XX_RATE" DOUBLE,
                "HTTP_5XX_RATE" DOUBLE,
                "UNIQUE_CLIENT_IPS" INTEGER,
                "UNIQUE_SERVICES" INTEGER,
                "UNIQUE_IP_SERVICE_PAIRS" INTEGER,
                "MAX_EVENTS_FROM_SINGLE_IP" INTEGER,
                "MAX_SERVICES_FROM_SINGLE_IP" INTEGER,
                "SUSPICIOUS_IP_COUNT" INTEGER,
                "AVG_EVENTS_PER_IP" DOUBLE,
                "AVG_EVENTS_PER_SERVICE" DOUBLE,
                "TOP_IP_EVENT_SHARE" DOUBLE,
                "TOP_SERVICE_EVENT_SHARE" DOUBLE,
                "SUSPICIOUS_IP_RATIO" DOUBLE,
                "IP_BURST_RATIO" DOUBLE,
                "PAIR_REUSE_RATIO" DOUBLE,
                "CLIENT_IP_ENTROPY" DOUBLE,
                "SERVICE_ENTROPY" DOUBLE,
                "LLM_REQUEST_COUNT" INTEGER,
                "LLM_TIMEOUT_COUNT" INTEGER,
                "LLM_ERROR_COUNT" INTEGER,
                "LLM_COST_PER_REQUEST" DOUBLE,
                "LLM_MODEL_ENTROPY" DOUBLE,
                "AVG_LLM_LATENCY_MS" DOUBLE,
                "P95_LLM_LATENCY_MS" DOUBLE,
                "TOTAL_LLM_COST_USD" DOUBLE,
                "SYSTEM_ERROR_RATE" DOUBLE,
                "LLM_TIMEOUT_RATE" DOUBLE,
                "LLM_ERROR_RATE" DOUBLE,
                "LLM_TIMEOUT_PLUS_ERROR_RATE" DOUBLE,
                "SECURITY_ERROR_RATIO" DOUBLE,
                "DELTA_TOTAL_RECORDS" DOUBLE,
                "DELTA_ERROR_COUNT" DOUBLE,
                "DELTA_SECURITY_COUNT" DOUBLE,
                "DELTA_UNIQUE_CLIENT_IPS" DOUBLE,
                "DELTA_UNIQUE_SERVICES" DOUBLE,
                "DELTA_AVG_LLM_LATENCY_MS" DOUBLE,
                "DELTA_P95_LLM_LATENCY_MS" DOUBLE,
                "DELTA_TOTAL_LLM_COST_USD" DOUBLE,
                "DELTA_TOP_IP_EVENT_SHARE" DOUBLE,
                "DELTA_LLM_TIMEOUT_PLUS_ERROR_RATE" DOUBLE,
                "RULE_SCORE" INTEGER,
                "FINAL_SCORE" INTEGER,
                "DECISION_SOURCE" NVARCHAR(40),
                "ML_MODEL_AVAILABLE" SMALLINT,
                "ML_TRAINING_ROW_COUNT" INTEGER,
                "ML_ANOMALY_SCORE" DOUBLE,
                "ML_CONFIDENCE_SCORE" DOUBLE,
                "ML_IS_ANOMALY" SMALLINT,
                "THREAT_SCORE" INTEGER,
                "DETECTION_COUNT" INTEGER,
                "ATTACK_PREDICTED" SMALLINT,
                "SUMMARY_JSON" NCLOB,
                "SAVED_AT_UTC" NVARCHAR(40)
            )
            ''',
            f'''
            CREATE COLUMN TABLE "{schema}"."DETECTIONS" (
                "DETECTION_ID" NVARCHAR(64) PRIMARY KEY,
                "WINDOW_KEY" NVARCHAR(64) NOT NULL,
                "RULE_NAME" NVARCHAR(120) NOT NULL,
                "SEVERITY" NVARCHAR(20) NOT NULL,
                "SCORE" INTEGER NOT NULL,
                "MESSAGE" NVARCHAR(1000) NOT NULL,
                "CONTEXT_JSON" NCLOB,
                "DETECTED_AT_UTC" NVARCHAR(40) NOT NULL
            )
            ''',
            f'''
            CREATE COLUMN TABLE "{schema}"."TRAINING_LABELS" (
                "WINDOW_KEY" NVARCHAR(64) PRIMARY KEY,
                "LABEL_ATTACK" SMALLINT NOT NULL,
                "LABEL_SOURCE" NVARCHAR(120),
                "LABEL_NOTES" NVARCHAR(1000),
                "LABELED_AT_UTC" NVARCHAR(40) NOT NULL
            )
            ''',
            f'''
            CREATE COLUMN TABLE "{schema}"."MODEL_RUNS" (
                "RUN_ID" NVARCHAR(64) PRIMARY KEY,
                "ALGORITHM" NVARCHAR(120) NOT NULL,
                "FEATURE_TABLE" NVARCHAR(120) NOT NULL,
                "TRAINING_ROW_COUNT" INTEGER NOT NULL,
                "CONTAMINATION" DOUBLE NOT NULL,
                "STATUS" NVARCHAR(40) NOT NULL,
                "DETAILS_JSON" NCLOB,
                "STARTED_AT_UTC" NVARCHAR(40) NOT NULL,
                "COMPLETED_AT_UTC" NVARCHAR(40)
            )
            ''',
            f'''
            CREATE COLUMN TABLE "{schema}"."MODEL_SCORES" (
                "RUN_ID" NVARCHAR(64) NOT NULL,
                "WINDOW_KEY" NVARCHAR(64) NOT NULL,
                "ANOMALY_SCORE" DOUBLE,
                "IS_ANOMALY" SMALLINT,
                "RAW_JSON" NCLOB,
                PRIMARY KEY ("RUN_ID", "WINDOW_KEY")
            )
            ''',
        ]

        for statement in table_statements:
            self._execute_ddl(statement)

    def upsert_raw_logs(self, records: list[dict[str, Any]], window: UtcWindow) -> None:
        if self.connection is None:
            return

        sql = f'''
        UPSERT "{self.config.schema}"."RAW_LOGS"
        (
            "LOG_ID",
            "WINDOW_KEY",
            "WINDOW_START_UTC",
            "WINDOW_END_UTC",
            "LOG_TIMESTAMP_UTC",
            "SAP_FUNCTION_LOG_TYPE",
            "IS_LLM_LOG",
            "IS_SYSTEM_LOG",
            "CLIENT_IP",
            "SERVICE_ID",
            "HTTP_STATUS_CODE",
            "LLM_MODEL_ID",
            "LLM_STATUS",
            "LLM_COST_USD",
            "LLM_RESPONSE_TIME_MS",
            "RAW_PAYLOAD_JSON"
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        WITH PRIMARY KEY
        '''

        cursor = self.connection.cursor()
        try:
            for record in records:
                log_id = str(record.get("_id") or uuid.uuid4())
                log_type = record.get("sap_function_log_type")
                is_llm_log = 1 if log_type in LLM_LOG_TYPES else 0
                is_system_log = 0 if is_llm_log else 1
                cursor.execute(
                    sql,
                    (
                        log_id,
                        window.key,
                        window.start.isoformat(),
                        window.end.isoformat(),
                        safe_str(record.get("@timestamp")),
                        safe_str(log_type),
                        is_llm_log,
                        is_system_log,
                        safe_str(record.get("client_ip")),
                        safe_str(record.get("service_id")),
                        safe_int(record.get("http_status_code")),
                        safe_str(record.get("llm_model_id")),
                        safe_str(record.get("llm_status")),
                        safe_float(record.get("llm_cost_usd")),
                        safe_float(record.get("llm_response_time_ms")),
                        json.dumps(record, ensure_ascii=True, default=str),
                    ),
                )
            self.connection.commit()
        finally:
            cursor.close()

    def upsert_window_metrics(self, metrics: dict[str, Any], saved_at_utc: str) -> None:
        if self.connection is None:
            return

        sql = f'''
        UPSERT "{self.config.schema}"."WINDOW_METRICS"
        (
            "WINDOW_KEY",
            "WINDOW_START_UTC",
            "WINDOW_END_UTC",
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
            "RULE_SCORE",
            "FINAL_SCORE",
            "DECISION_SOURCE",
            "ML_MODEL_AVAILABLE",
            "ML_TRAINING_ROW_COUNT",
            "ML_ANOMALY_SCORE",
            "ML_CONFIDENCE_SCORE",
            "ML_IS_ANOMALY",
            "THREAT_SCORE",
            "DETECTION_COUNT",
            "ATTACK_PREDICTED",
            "SUMMARY_JSON",
            "SAVED_AT_UTC"
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        WITH PRIMARY KEY
        '''

        params = (
            metrics["window_key"],
            metrics["window_start_utc"],
            metrics["window_end_utc"],
            metrics["total_records"],
            metrics["system_log_count"],
            metrics["llm_log_count"],
            metrics["error_count"],
            metrics["security_count"],
            metrics["warning_count"],
            metrics["audit_count"],
            metrics.get("debug_count", 0),
            metrics.get("perf_count", 0),
            metrics["http_4xx_count"],
            metrics["http_5xx_count"],
            metrics.get("http_4xx_rate", 0.0),
            metrics.get("http_5xx_rate", 0.0),
            metrics["unique_client_ips"],
            metrics["unique_services"],
            metrics.get("unique_ip_service_pairs", 0),
            metrics["max_events_from_single_ip"],
            metrics["max_services_from_single_ip"],
            metrics["suspicious_ip_count"],
            metrics.get("avg_events_per_ip", 0.0),
            metrics.get("avg_events_per_service", 0.0),
            metrics.get("top_ip_event_share", 0.0),
            metrics.get("top_service_event_share", 0.0),
            metrics.get("suspicious_ip_ratio", 0.0),
            metrics.get("ip_burst_ratio", 0.0),
            metrics.get("pair_reuse_ratio", 0.0),
            metrics.get("client_ip_entropy", 0.0),
            metrics.get("service_entropy", 0.0),
            metrics["llm_request_count"],
            metrics["llm_timeout_count"],
            metrics["llm_error_count"],
            metrics.get("llm_cost_per_request", 0.0),
            metrics.get("llm_model_entropy", 0.0),
            metrics["avg_llm_latency_ms"],
            metrics["p95_llm_latency_ms"],
            metrics["total_llm_cost_usd"],
            metrics["system_error_rate"],
            metrics["llm_timeout_rate"],
            metrics["llm_error_rate"],
            metrics.get("llm_timeout_plus_error_rate", 0.0),
            metrics.get("security_error_ratio", 0.0),
            metrics.get("delta_total_records", 0.0),
            metrics.get("delta_error_count", 0.0),
            metrics.get("delta_security_count", 0.0),
            metrics.get("delta_unique_client_ips", 0.0),
            metrics.get("delta_unique_services", 0.0),
            metrics.get("delta_avg_llm_latency_ms", 0.0),
            metrics.get("delta_p95_llm_latency_ms", 0.0),
            metrics.get("delta_total_llm_cost_usd", 0.0),
            metrics.get("delta_top_ip_event_share", 0.0),
            metrics.get("delta_llm_timeout_plus_error_rate", 0.0),
            metrics.get("rule_score", 0),
            metrics.get("final_score", metrics.get("threat_score", 0)),
            metrics.get("decision_source", "rules_only"),
            1 if metrics.get("ml_model_available", False) else 0,
            metrics.get("ml_training_row_count", 0),
            metrics.get("ml_anomaly_score", 0.0),
            metrics.get("ml_confidence_score", 0.0),
            1 if metrics.get("ml_is_anomaly", False) else 0,
            metrics["threat_score"],
            metrics["detection_count"],
            1 if metrics["attack_predicted"] else 0,
            json.dumps(metrics, ensure_ascii=True, default=str),
            saved_at_utc,
        )

        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            self.connection.commit()
        finally:
            cursor.close()

    def upsert_detections(self, detections: list[dict[str, Any]]) -> None:
        if self.connection is None or not detections:
            return

        sql = f'''
        UPSERT "{self.config.schema}"."DETECTIONS"
        (
            "DETECTION_ID",
            "WINDOW_KEY",
            "RULE_NAME",
            "SEVERITY",
            "SCORE",
            "MESSAGE",
            "CONTEXT_JSON",
            "DETECTED_AT_UTC"
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        WITH PRIMARY KEY
        '''

        cursor = self.connection.cursor()
        try:
            for detection in detections:
                cursor.execute(
                    sql,
                    (
                        detection["detection_id"],
                        detection["window_key"],
                        detection["rule_name"],
                        detection["severity"],
                        detection["score"],
                        detection["message"],
                        json.dumps(detection["context"], ensure_ascii=True, default=str),
                        detection["detected_at_utc"],
                    ),
                )
            self.connection.commit()
        finally:
            cursor.close()

    def upsert_model_run(self, run_record: dict[str, Any]) -> None:
        if self.connection is None:
            return

        sql = f'''
        UPSERT "{self.config.schema}"."MODEL_RUNS"
        (
            "RUN_ID",
            "ALGORITHM",
            "FEATURE_TABLE",
            "TRAINING_ROW_COUNT",
            "CONTAMINATION",
            "STATUS",
            "DETAILS_JSON",
            "STARTED_AT_UTC",
            "COMPLETED_AT_UTC"
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        WITH PRIMARY KEY
        '''

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                sql,
                (
                    run_record["run_id"],
                    run_record["algorithm"],
                    run_record["feature_table"],
                    run_record["training_row_count"],
                    run_record["contamination"],
                    run_record["status"],
                    json.dumps(run_record.get("details", {}), ensure_ascii=True, default=str),
                    run_record["started_at_utc"],
                    run_record.get("completed_at_utc"),
                ),
            )
            self.connection.commit()
        finally:
            cursor.close()

    def upsert_model_scores(self, run_id: str, score_rows: list[dict[str, Any]]) -> None:
        if self.connection is None or not score_rows:
            return

        sql = f'''
        UPSERT "{self.config.schema}"."MODEL_SCORES"
        (
            "RUN_ID",
            "WINDOW_KEY",
            "ANOMALY_SCORE",
            "IS_ANOMALY",
            "RAW_JSON"
        )
        VALUES (?, ?, ?, ?, ?)
        WITH PRIMARY KEY
        '''

        cursor = self.connection.cursor()
        try:
            for row in score_rows:
                cursor.execute(
                    sql,
                    (
                        run_id,
                        row["window_key"],
                        row.get("anomaly_score"),
                        row.get("is_anomaly"),
                        json.dumps(row.get("raw", {}), ensure_ascii=True, default=str),
                    ),
                )
            self.connection.commit()
        finally:
            cursor.close()

    def _execute_ddl(self, sql: str) -> None:
        if self.connection is None:
            return

        cursor = self.connection.cursor()
        try:
            cursor.execute(sql)
            self.connection.commit()
        except Exception as exc:
            message = str(exc).lower()
            if "already exists" not in message and "duplicate name" not in message:
                raise
            self.connection.rollback()
        finally:
            cursor.close()
