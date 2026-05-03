from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from backend.core.config import Settings
from backend.services.ingestion.features import NUMERIC_FEATURE_COLUMNS


class BaseStore(ABC):
    @abstractmethod
    def ensure_schema(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_raw_logs(self, records: List[Dict[str, Any]]) -> int:
        raise NotImplementedError

    @abstractmethod
    def bulk_upsert_raw_logs(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        raise NotImplementedError

    @abstractmethod
    def insert_ingest_run(self, ingest_run: Dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def insert_alerts(self, alerts: List[Dict[str, Any]]) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_last_run(self) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def upsert_window_metrics(self, metrics: Dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def bulk_upsert_window_metrics(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_recent_window_metrics(self, limit: int = 200) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_alerts(self, limit: int = 200) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_ingest_runs(self, limit: int = 200) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_dashboard_summary(self, time_window_hours: int = 24) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_window_features(self, limit: int = 200) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_window_metrics(self) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def call_cleanup_procedure(self, retention_days: int = 90) -> Dict[str, Any]:
        raise NotImplementedError


class SqliteStore(BaseStore):
    def __init__(self, sqlite_path: str) -> None:
        self.sqlite_path = sqlite_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_logs (
                    log_id TEXT PRIMARY KEY,
                    log_ts TEXT,
                    payload TEXT NOT NULL,
                    is_llm_log INTEGER NOT NULL,
                    is_system_log INTEGER NOT NULL,
                    ingested_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    ended_at_utc TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    window_start TEXT,
                    window_end TEXT,
                    total_pages_expected INTEGER NOT NULL,
                    total_pages_fetched INTEGER NOT NULL,
                    total_records_info INTEGER NOT NULL,
                    total_records_fetched INTEGER NOT NULL,
                    error_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts_events (
                    alert_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    detected_at_utc TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS window_metrics (
                    window_key TEXT PRIMARY KEY,
                    window_start TEXT,
                    window_end TEXT,
                    total_records INTEGER NOT NULL,
                    threat_score INTEGER NOT NULL,
                    attack_predicted INTEGER NOT NULL,
                    model_available INTEGER NOT NULL,
                    is_anomaly INTEGER NOT NULL,
                    anomaly_score REAL NOT NULL,
                    anomaly_percentile REAL NOT NULL,
                    summary_json TEXT NOT NULL,
                    saved_at_utc TEXT NOT NULL
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS window_features (
                    window_key TEXT PRIMARY KEY,
                    {", ".join(f"{column} REAL NOT NULL" for column in NUMERIC_FEATURE_COLUMNS)},
                    saved_at_utc TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_logs_log_ts ON raw_logs(log_ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON ingest_runs(started_at_utc)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_window_metrics_saved ON window_metrics(saved_at_utc)")
            conn.commit()

    def upsert_raw_logs(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0

        upserted = 0
        with self._connect() as conn:
            for record in records:
                log_id = str(record.get("_id") or self._fallback_id(record))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO raw_logs
                    (log_id, log_ts, payload, is_llm_log, is_system_log, ingested_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        log_id,
                        record.get("@timestamp"),
                        json.dumps(record, ensure_ascii=True),
                        int(bool(record.get("is_llm_log", False))),
                        int(bool(record.get("is_system_log", False))),
                        record.get("ingested_at") or datetime.utcnow().isoformat(),
                    ),
                )
                upserted += 1
            conn.commit()
        return upserted

    def bulk_upsert_raw_logs(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        if not records:
            return 0

        total = 0
        step = max(1, int(batch_size))
        for start in range(0, len(records), step):
            total += self.upsert_raw_logs(records[start:start + step])
        return total

    def insert_ingest_run(self, ingest_run: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ingest_runs
                (run_id, status, started_at_utc, ended_at_utc, duration_seconds, window_start,
                 window_end, total_pages_expected, total_pages_fetched, total_records_info,
                 total_records_fetched, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ingest_run.get("run_id"),
                    ingest_run.get("status"),
                    ingest_run.get("started_at_utc"),
                    ingest_run.get("ended_at_utc"),
                    ingest_run.get("duration_seconds"),
                    ingest_run.get("window_start"),
                    ingest_run.get("window_end"),
                    ingest_run.get("total_pages_expected", 0),
                    ingest_run.get("total_pages_fetched", 0),
                    ingest_run.get("total_records_info", 0),
                    ingest_run.get("total_records_fetched", 0),
                    ingest_run.get("error_message"),
                ),
            )
            conn.commit()

    def insert_alerts(self, alerts: List[Dict[str, Any]]) -> int:
        if not alerts:
            return 0
        inserted = 0
        with self._connect() as conn:
            for alert in alerts:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO alerts_events
                    (alert_id, run_id, detected_at_utc, alert_type, severity, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alert.get("alert_id"),
                        alert.get("run_id"),
                        alert.get("detected_at_utc"),
                        alert.get("alert_type"),
                        alert.get("severity"),
                        json.dumps(alert.get("payload", {}), ensure_ascii=True),
                    ),
                )
                inserted += 1
            conn.commit()
        return inserted

    def get_last_run(self) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, status, started_at_utc, ended_at_utc, duration_seconds,
                       window_start, window_end, total_pages_expected, total_pages_fetched,
                       total_records_info, total_records_fetched, error_message
                FROM ingest_runs
                ORDER BY started_at_utc DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def upsert_window_metrics(self, metrics: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO window_metrics
                (window_key, window_start, window_end, total_records, threat_score, attack_predicted,
                 model_available, is_anomaly, anomaly_score, anomaly_percentile, summary_json, saved_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics.get("window_key"),
                    metrics.get("window_start"),
                    metrics.get("window_end"),
                    int(metrics.get("total_records", 0)),
                    int(metrics.get("threat_score", 0)),
                    int(bool(metrics.get("attack_predicted", False))),
                    int(bool(metrics.get("model_available", False))),
                    int(bool(metrics.get("is_anomaly", False))),
                    float(metrics.get("anomaly_score", 0.0)),
                    float(metrics.get("anomaly_percentile", 0.0)),
                    json.dumps(metrics, ensure_ascii=True),
                    metrics.get("saved_at_utc") or datetime.utcnow().isoformat(),
                ),
            )
            feature_columns = ", ".join(NUMERIC_FEATURE_COLUMNS)
            feature_placeholders = ", ".join("?" for _ in NUMERIC_FEATURE_COLUMNS)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO window_features
                (window_key, {feature_columns}, saved_at_utc)
                VALUES (?, {feature_placeholders}, ?)
                """,
                (
                    metrics.get("window_key"),
                    *[float(metrics.get(column, 0.0) or 0.0) for column in NUMERIC_FEATURE_COLUMNS],
                    metrics.get("saved_at_utc") or datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def bulk_upsert_window_metrics(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        if not records:
            return 0

        total = 0
        step = max(1, int(batch_size))
        for start in range(0, len(records), step):
            batch = records[start:start + step]
            for metrics in batch:
                self.upsert_window_metrics(metrics)
                total += 1
        return total

    def get_recent_window_metrics(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT summary_json
                FROM window_metrics
                ORDER BY saved_at_utc DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [json.loads(row["summary_json"]) for row in rows]

    def get_recent_alerts(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT alert_id, run_id, detected_at_utc, alert_type, severity, payload
                FROM alerts_events
                ORDER BY detected_at_utc DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        alerts: List[Dict[str, Any]] = []
        for row in rows:
            alert = dict(row)
            payload = alert.get("payload")
            if isinstance(payload, str):
                try:
                    alert["payload"] = json.loads(payload)
                except json.JSONDecodeError:
                    pass
            alerts.append(alert)
        return alerts

    def get_recent_ingest_runs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, status, started_at_utc, ended_at_utc, duration_seconds,
                       window_start, window_end, total_pages_expected, total_pages_fetched,
                       total_records_info, total_records_fetched, error_message
                FROM ingest_runs
                ORDER BY started_at_utc DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_dashboard_summary(self, time_window_hours: int = 24) -> Dict[str, Any]:
        with self._connect() as conn:
            # Total alerts in time window
            total_alerts_row = conn.execute(
                """
                SELECT COUNT(*) as count
                FROM alerts_events
                WHERE datetime(detected_at_utc) > datetime('now', '-' || ? || ' hours')
                """,
                (int(time_window_hours),),
            ).fetchone()
            total_alerts = total_alerts_row["count"] if total_alerts_row else 0
            
            # Alerts by severity
            severity_rows = conn.execute(
                """
                SELECT severity, COUNT(*) as count
                FROM alerts_events
                WHERE datetime(detected_at_utc) > datetime('now', '-' || ? || ' hours')
                GROUP BY severity
                """,
                (int(time_window_hours),),
            ).fetchall()
            alerts_by_severity = {row["severity"]: row["count"] for row in severity_rows}
            
            # Latest metrics
            top_metrics_row = conn.execute(
                """
                SELECT summary_json
                FROM window_metrics
                ORDER BY saved_at_utc DESC
                LIMIT 1
                """
            ).fetchone()
            top_metrics = json.loads(top_metrics_row["summary_json"]) if top_metrics_row else {}
            
            # Last run status
            last_run_row = conn.execute(
                """
                SELECT run_id, status, started_at_utc, ended_at_utc, duration_seconds, error_message
                FROM ingest_runs
                ORDER BY started_at_utc DESC
                LIMIT 1
                """
            ).fetchone()
            last_run = dict(last_run_row) if last_run_row else {}
        
        return {
            "total_alerts": total_alerts,
            "alerts_by_severity": alerts_by_severity,
            "top_metrics": top_metrics,
            "last_run": last_run,
            "generated_at": datetime.utcnow().isoformat()
        }

    def get_recent_window_features(self, limit: int = 200) -> List[Dict[str, Any]]:
        feature_columns = ", ".join(NUMERIC_FEATURE_COLUMNS)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT window_key, {feature_columns}, saved_at_utc
                FROM window_features
                ORDER BY saved_at_utc DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_window_metrics(self) -> Optional[Dict[str, Any]]:
        results = self.get_recent_window_metrics(limit=1)
        return results[0] if results else None

    def call_cleanup_procedure(self, retention_days: int = 90) -> Dict[str, Any]:
        cutoff = datetime.utcnow().timestamp() - (max(1, int(retention_days)) * 86400)
        cutoff_iso = datetime.utcfromtimestamp(cutoff).isoformat()

        deleted_counts: Dict[str, int] = {}
        with self._connect() as conn:
            cursor = conn.cursor()
            for table_name, column_name, key in (
                ("alerts_events", "detected_at_utc", "alerts_events"),
                ("window_metrics", "window_start", "window_metrics"),
                ("raw_logs", "log_ts", "raw_logs"),
            ):
                cursor.execute(
                    f'DELETE FROM {table_name} WHERE {column_name} < ?',
                    (cutoff_iso,),
                )
                deleted_counts[key] = cursor.rowcount if cursor.rowcount is not None else 0

            try:
                cursor.execute("DELETE FROM ingest_runs WHERE ended_at_utc < ?", (cutoff_iso,))
                deleted_counts["ingest_runs"] = cursor.rowcount if cursor.rowcount is not None else 0
            except sqlite3.OperationalError:
                deleted_counts["ingest_runs"] = 0
            conn.commit()

        return {
            "status": "cleaned",
            "retention_days": max(1, int(retention_days)),
            "rows_deleted": sum(deleted_counts.values()),
            "deleted_counts": deleted_counts,
            "cutoff_utc": cutoff_iso,
        }

    @staticmethod
    def _fallback_id(record: Dict[str, Any]) -> str:
        payload = json.dumps(record, sort_keys=True, ensure_ascii=True)
        return str(abs(hash(payload)))


class HanaStore(BaseStore):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _connect(self):
        try:
            from hdbcli import dbapi
        except ImportError as exc:
            raise RuntimeError(
                "hdbcli is required for STORAGE_BACKEND=hana. Install requirements-hana.txt"
            ) from exc

        return dbapi.connect(
            address=self.settings.hana_host,
            port=self.settings.hana_port,
            user=self.settings.hana_user,
            password=self.settings.hana_password,
            encrypt=self.settings.hana_encrypt,
            sslValidateCertificate=self.settings.hana_validate_certificate,
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        conn = self._connect()
        try:
            yield conn
        except Exception:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                try:
                    rollback()
                except Exception:
                    pass
            raise
        finally:
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    def ensure_schema(self) -> None:
        schema = self.settings.hana_schema
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(f'CREATE SCHEMA "{schema}"')
            except Exception:
                pass

            statements = [
                f'''
                CREATE COLUMN TABLE "{schema}"."RAW_LOGS" (
                    LOG_ID NVARCHAR(128) PRIMARY KEY,
                    LOG_TS NVARCHAR(64),
                    PAYLOAD NCLOB,
                    IS_LLM_LOG TINYINT,
                    IS_SYSTEM_LOG TINYINT,
                    INGESTED_AT NVARCHAR(64)
                )
                ''',
                f'''
                CREATE COLUMN TABLE "{schema}"."INGEST_RUNS" (
                    RUN_ID NVARCHAR(64) PRIMARY KEY,
                    STATUS NVARCHAR(32),
                    STARTED_AT_UTC NVARCHAR(64),
                    ENDED_AT_UTC NVARCHAR(64),
                    DURATION_SECONDS DOUBLE,
                    WINDOW_START NVARCHAR(64),
                    WINDOW_END NVARCHAR(64),
                    TOTAL_PAGES_EXPECTED INTEGER,
                    TOTAL_PAGES_FETCHED INTEGER,
                    TOTAL_RECORDS_INFO INTEGER,
                    TOTAL_RECORDS_FETCHED INTEGER,
                    ERROR_MESSAGE NCLOB
                )
                ''',
                f'''
                CREATE COLUMN TABLE "{schema}"."ALERTS_EVENTS" (
                    ALERT_ID NVARCHAR(64) PRIMARY KEY,
                    RUN_ID NVARCHAR(64),
                    DETECTED_AT_UTC NVARCHAR(64),
                    ALERT_TYPE NVARCHAR(128),
                    SEVERITY NVARCHAR(16),
                    PAYLOAD NCLOB
                )
                ''',
                f'''
                CREATE COLUMN TABLE "{schema}"."WINDOW_METRICS" (
                    WINDOW_KEY NVARCHAR(128) PRIMARY KEY,
                    WINDOW_START NVARCHAR(64),
                    WINDOW_END NVARCHAR(64),
                    TOTAL_RECORDS INTEGER,
                    THREAT_SCORE INTEGER,
                    ATTACK_PREDICTED TINYINT,
                    MODEL_AVAILABLE TINYINT,
                    IS_ANOMALY TINYINT,
                    ANOMALY_SCORE DOUBLE,
                    ANOMALY_PERCENTILE DOUBLE,
                    SUMMARY_JSON NCLOB,
                    SAVED_AT_UTC NVARCHAR(64)
                )
                ''',
                f'''
                CREATE COLUMN TABLE "{schema}"."WINDOW_FEATURES" (
                    WINDOW_KEY NVARCHAR(128) PRIMARY KEY,
                    TOTAL_RECORDS DOUBLE,
                    SYSTEM_LOG_COUNT DOUBLE,
                    LLM_LOG_COUNT DOUBLE,
                    ERROR_COUNT DOUBLE,
                    SECURITY_COUNT DOUBLE,
                    WARNING_COUNT DOUBLE,
                    AUDIT_COUNT DOUBLE,
                    DEBUG_COUNT DOUBLE,
                    PERF_COUNT DOUBLE,
                    HTTP_4XX_COUNT DOUBLE,
                    HTTP_5XX_COUNT DOUBLE,
                    MAX_EVENTS_FROM_SINGLE_IP DOUBLE,
                    LLM_REQUEST_COUNT DOUBLE,
                    LLM_ERROR_COUNT DOUBLE,
                    LLM_TIMEOUT_COUNT DOUBLE,
                    AVG_LLM_LATENCY_MS DOUBLE,
                    P95_LLM_LATENCY_MS DOUBLE,
                    TOTAL_LLM_COST_USD DOUBLE,
                    SYSTEM_ERROR_RATE DOUBLE,
                    SECURITY_EVENT_RATE DOUBLE,
                    LLM_ERROR_RATE DOUBLE,
                    LLM_TIMEOUT_RATE DOUBLE,
                    TOP_IP_EVENT_SHARE DOUBLE,
                    SAVED_AT_UTC NVARCHAR(64)
                )
                ''',
            ]

            for statement in statements:
                try:
                    cursor.execute(statement)
                except Exception:
                    pass

            conn.commit()

    def upsert_raw_logs(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0

        schema = self.settings.hana_schema
        upserted = 0
        with self._connection() as conn:
            cursor = conn.cursor()
            statement = (
                f'UPSERT "{schema}"."RAW_LOGS" '
                '(LOG_ID, LOG_TS, PAYLOAD, IS_LLM_LOG, IS_SYSTEM_LOG, INGESTED_AT) '
                'VALUES (?, ?, ?, ?, ?, ?) WITH PRIMARY KEY'
            )
            for record in records:
                log_id = str(record.get("_id") or SqliteStore._fallback_id(record))
                cursor.execute(
                    statement,
                    (
                        log_id,
                        record.get("@timestamp"),
                        json.dumps(record, ensure_ascii=True),
                        int(bool(record.get("is_llm_log", False))),
                        int(bool(record.get("is_system_log", False))),
                        record.get("ingested_at") or datetime.utcnow().isoformat(),
                    ),
                )
                upserted += 1
            conn.commit()
        return upserted

    def bulk_upsert_raw_logs(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        if not records:
            return 0

        schema = self.settings.hana_schema
        total = 0
        step = max(1, int(batch_size))
        statement = (
            f'UPSERT "{schema}"."RAW_LOGS" '
            '(LOG_ID, LOG_TS, PAYLOAD, IS_LLM_LOG, IS_SYSTEM_LOG, INGESTED_AT) '
            'VALUES (?, ?, ?, ?, ?, ?) WITH PRIMARY KEY'
        )
        with self._connection() as conn:
            cursor = conn.cursor()
            for start in range(0, len(records), step):
                batch = records[start:start + step]
                params = []
                for record in batch:
                    log_id = str(record.get("_id") or SqliteStore._fallback_id(record))
                    params.append(
                        (
                            log_id,
                            record.get("@timestamp"),
                            json.dumps(record, ensure_ascii=True),
                            int(bool(record.get("is_llm_log", False))),
                            int(bool(record.get("is_system_log", False))),
                            record.get("ingested_at") or datetime.utcnow().isoformat(),
                        )
                    )
                cursor.executemany(statement, params)
                total += len(batch)
            conn.commit()
        return total

    def insert_ingest_run(self, ingest_run: Dict[str, Any]) -> None:
        schema = self.settings.hana_schema
        with self._connection() as conn:
            cursor = conn.cursor()
            statement = (
                f'UPSERT "{schema}"."INGEST_RUNS" '
                '(RUN_ID, STATUS, STARTED_AT_UTC, ENDED_AT_UTC, DURATION_SECONDS, WINDOW_START, '
                'WINDOW_END, TOTAL_PAGES_EXPECTED, TOTAL_PAGES_FETCHED, TOTAL_RECORDS_INFO, '
                'TOTAL_RECORDS_FETCHED, ERROR_MESSAGE) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) WITH PRIMARY KEY'
            )
            cursor.execute(
                statement,
                (
                    ingest_run.get("run_id"),
                    ingest_run.get("status"),
                    ingest_run.get("started_at_utc"),
                    ingest_run.get("ended_at_utc"),
                    ingest_run.get("duration_seconds"),
                    ingest_run.get("window_start"),
                    ingest_run.get("window_end"),
                    ingest_run.get("total_pages_expected", 0),
                    ingest_run.get("total_pages_fetched", 0),
                    ingest_run.get("total_records_info", 0),
                    ingest_run.get("total_records_fetched", 0),
                    ingest_run.get("error_message"),
                ),
            )
            conn.commit()

    def insert_alerts(self, alerts: List[Dict[str, Any]]) -> int:
        if not alerts:
            return 0

        schema = self.settings.hana_schema
        inserted = 0
        with self._connection() as conn:
            cursor = conn.cursor()
            statement = (
                f'UPSERT "{schema}"."ALERTS_EVENTS" '
                '(ALERT_ID, RUN_ID, DETECTED_AT_UTC, ALERT_TYPE, SEVERITY, PAYLOAD) '
                'VALUES (?, ?, ?, ?, ?, ?) WITH PRIMARY KEY'
            )
            for alert in alerts:
                cursor.execute(
                    statement,
                    (
                        alert.get("alert_id"),
                        alert.get("run_id"),
                        alert.get("detected_at_utc"),
                        alert.get("alert_type"),
                        alert.get("severity"),
                        json.dumps(alert.get("payload", {}), ensure_ascii=True),
                    ),
                )
                inserted += 1
            conn.commit()
        return inserted

    def get_last_run(self) -> Optional[Dict[str, Any]]:
        schema = self.settings.hana_schema
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT RUN_ID, STATUS, STARTED_AT_UTC, ENDED_AT_UTC, DURATION_SECONDS,
                       WINDOW_START, WINDOW_END, TOTAL_PAGES_EXPECTED, TOTAL_PAGES_FETCHED,
                       TOTAL_RECORDS_INFO, TOTAL_RECORDS_FETCHED, ERROR_MESSAGE
                FROM "{schema}"."INGEST_RUNS"
                ORDER BY STARTED_AT_UTC DESC
                LIMIT 1
                '''
            )
            row = cursor.fetchone()
            if not row:
                return None
            keys = [
                "run_id",
                "status",
                "started_at_utc",
                "ended_at_utc",
                "duration_seconds",
                "window_start",
                "window_end",
                "total_pages_expected",
                "total_pages_fetched",
                "total_records_info",
                "total_records_fetched",
                "error_message",
            ]
            return dict(zip(keys, row))

    def upsert_window_metrics(self, metrics: Dict[str, Any]) -> None:
        schema = self.settings.hana_schema
        with self._connection() as conn:
            cursor = conn.cursor()
            statement = (
                f'UPSERT "{schema}"."WINDOW_METRICS" '
                '(WINDOW_KEY, WINDOW_START, WINDOW_END, TOTAL_RECORDS, THREAT_SCORE, ATTACK_PREDICTED, '
                'MODEL_AVAILABLE, IS_ANOMALY, ANOMALY_SCORE, ANOMALY_PERCENTILE, SUMMARY_JSON, SAVED_AT_UTC) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) WITH PRIMARY KEY'
            )
            cursor.execute(
                statement,
                (
                    metrics.get("window_key"),
                    metrics.get("window_start"),
                    metrics.get("window_end"),
                    int(metrics.get("total_records", 0)),
                    int(metrics.get("threat_score", 0)),
                    int(bool(metrics.get("attack_predicted", False))),
                    int(bool(metrics.get("model_available", False))),
                    int(bool(metrics.get("is_anomaly", False))),
                    float(metrics.get("anomaly_score", 0.0)),
                    float(metrics.get("anomaly_percentile", 0.0)),
                    json.dumps(metrics, ensure_ascii=True),
                    metrics.get("saved_at_utc") or datetime.utcnow().isoformat(),
                ),
            )
            feature_columns = [column.upper() for column in NUMERIC_FEATURE_COLUMNS]
            feature_column_sql = ", ".join(feature_columns)
            feature_placeholders = ", ".join("?" for _ in feature_columns)
            feature_statement = (
                f'UPSERT "{schema}"."WINDOW_FEATURES" '
                f'(WINDOW_KEY, {feature_column_sql}, SAVED_AT_UTC) '
                f'VALUES (?, {feature_placeholders}, ?) '
                'WITH PRIMARY KEY'
            )
            cursor.execute(
                feature_statement,
                (
                    metrics.get("window_key"),
                    *[float(metrics.get(column, 0.0) or 0.0) for column in NUMERIC_FEATURE_COLUMNS],
                    metrics.get("saved_at_utc") or datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def bulk_upsert_window_metrics(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        if not records:
            return 0

        total = 0
        step = max(1, int(batch_size))
        for start in range(0, len(records), step):
            batch = records[start:start + step]
            for metrics in batch:
                self.upsert_window_metrics(metrics)
                total += 1
        return total

    def get_recent_window_metrics(self, limit: int = 200) -> List[Dict[str, Any]]:
        schema = self.settings.hana_schema
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT SUMMARY_JSON
                FROM "{schema}"."WINDOW_METRICS"
                ORDER BY SAVED_AT_UTC DESC
                LIMIT {int(limit)}
                '''
            )
            rows = cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_recent_alerts(self, limit: int = 200) -> List[Dict[str, Any]]:
        schema = self.settings.hana_schema
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT ALERT_ID, RUN_ID, DETECTED_AT_UTC, ALERT_TYPE, SEVERITY, PAYLOAD
                FROM "{schema}"."ALERTS_EVENTS"
                ORDER BY DETECTED_AT_UTC DESC
                LIMIT {int(limit)}
                '''
            )
            rows = cursor.fetchall()
            keys = [desc[0].lower() for desc in cursor.description]
        alerts: List[Dict[str, Any]] = []
        for row in rows:
            alert = dict(zip(keys, row))
            payload = alert.get("payload")
            if isinstance(payload, str):
                try:
                    alert["payload"] = json.loads(payload)
                except json.JSONDecodeError:
                    pass
            alerts.append(alert)
        return alerts

    def get_recent_ingest_runs(self, limit: int = 200) -> List[Dict[str, Any]]:
        schema = self.settings.hana_schema
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT RUN_ID, STATUS, STARTED_AT_UTC, ENDED_AT_UTC, DURATION_SECONDS,
                       WINDOW_START, WINDOW_END, TOTAL_PAGES_EXPECTED, TOTAL_PAGES_FETCHED,
                       TOTAL_RECORDS_INFO, TOTAL_RECORDS_FETCHED, ERROR_MESSAGE
                FROM "{schema}"."INGEST_RUNS"
                ORDER BY STARTED_AT_UTC DESC
                LIMIT {int(limit)}
                '''
            )
            rows = cursor.fetchall()
            keys = [desc[0].lower() for desc in cursor.description]
        return [dict(zip(keys, row)) for row in rows]

    def get_dashboard_summary(self, time_window_hours: int = 24) -> Dict[str, Any]:
        schema = self.settings.hana_schema
        with self._connection() as conn:
            cursor = conn.cursor()
            
            # Total alerts in time window
            cursor.execute(
                f'''
                SELECT COUNT(*) as count
                FROM "{schema}"."ALERTS_EVENTS"
                WHERE DETECTED_AT_UTC > ADD_SECONDS(CURRENT_TIMESTAMP, -{int(time_window_hours) * 3600})
                '''
            )
            total_alerts = cursor.fetchone()[0] or 0
            
            # Alerts by severity
            cursor.execute(
                f'''
                SELECT SEVERITY, COUNT(*) as count
                FROM "{schema}"."ALERTS_EVENTS"
                WHERE DETECTED_AT_UTC > ADD_SECONDS(CURRENT_TIMESTAMP, -{int(time_window_hours) * 3600})
                GROUP BY SEVERITY
                '''
            )
            alerts_by_severity = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Latest metrics
            cursor.execute(
                f'''
                SELECT SUMMARY_JSON
                FROM "{schema}"."WINDOW_METRICS"
                ORDER BY SAVED_AT_UTC DESC
                LIMIT 1
                '''
            )
            top_metrics_row = cursor.fetchone()
            top_metrics = json.loads(top_metrics_row[0]) if top_metrics_row else {}
            
            # Last run status
            cursor.execute(
                f'''
                SELECT RUN_ID, STATUS, STARTED_AT_UTC, ENDED_AT_UTC, DURATION_SECONDS, ERROR_MESSAGE
                FROM "{schema}"."INGEST_RUNS"
                ORDER BY STARTED_AT_UTC DESC
                LIMIT 1
                '''
            )
            last_run_row = cursor.fetchone()
            if last_run_row:
                keys = [desc[0].lower() for desc in cursor.description]
                last_run = dict(zip(keys, last_run_row))
            else:
                last_run = {}
        
        return {
            "total_alerts": total_alerts,
            "alerts_by_severity": alerts_by_severity,
            "top_metrics": top_metrics,
            "last_run": last_run,
            "generated_at": datetime.utcnow().isoformat()
        }

    def get_recent_window_features(self, limit: int = 200) -> List[Dict[str, Any]]:
        schema = self.settings.hana_schema
        feature_columns = [column.upper() for column in NUMERIC_FEATURE_COLUMNS]
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT WINDOW_KEY, {", ".join(feature_columns)}, SAVED_AT_UTC
                FROM "{schema}"."WINDOW_FEATURES"
                ORDER BY SAVED_AT_UTC DESC
                LIMIT {int(limit)}
                '''
            )
            rows = cursor.fetchall()
            keys = [desc[0].lower() for desc in cursor.description]
        return [dict(zip(keys, row)) for row in rows]

    def get_latest_window_metrics(self) -> Optional[Dict[str, Any]]:
        results = self.get_recent_window_metrics(limit=1)
        return results[0] if results else None

    def call_cleanup_procedure(self, retention_days: int = 90) -> Dict[str, Any]:
        schema = self.settings.hana_schema
        retention_days = max(1, int(retention_days))
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'CALL "{schema}"."sp_cleanup_old_data"(p_retention_days => {retention_days})')

            deleted_counts: Dict[str, int] = {}
            try:
                cursor.execute(
                    f'SELECT TOP 50 "DETAILS" FROM "{schema}"."AUDIT_LOG" ORDER BY "TIMESTAMP" DESC'
                )
                rows = cursor.fetchall()
                details = [row[0] for row in rows]
            except Exception:
                details = []

        rows_deleted = 0
        for detail in details:
            if detail.startswith("Deleted "):
                parts = detail.split()
                if len(parts) >= 3 and parts[1].isdigit():
                    rows_deleted += int(parts[1])
        return {
            "status": "cleaned",
            "retention_days": int(retention_days),
            "rows_deleted": rows_deleted,
            "deleted_counts": deleted_counts,
        }


def create_store(settings: Settings) -> BaseStore:
    if settings.storage_backend == "hana":
        return HanaStore(settings)
    return SqliteStore(settings.sqlite_path)
