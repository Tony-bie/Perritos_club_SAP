from __future__ import annotations

import hashlib
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

    def sync_fallback_to_primary(self) -> Dict[str, Any]:
        return {
            "status": "not_supported",
            "synced_counts": {},
            "pending_counts": {},
        }

    def get_fallback_status(self) -> Dict[str, Any]:
        return {
            "enabled": False,
            "pending_counts": {},
        }


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
                    run_id TEXT,
                    window_start TEXT,
                    window_end TEXT,
                    total_records INTEGER NOT NULL,
                    threat_score INTEGER NOT NULL,
                    detection_count INTEGER NOT NULL DEFAULT 0,
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
                    run_id TEXT,
                    {", ".join(f"{column} REAL NOT NULL" for column in NUMERIC_FEATURE_COLUMNS)},
                    saved_at_utc TEXT NOT NULL
                )
                """
            )
            self._ensure_sqlite_column(conn, "window_metrics", "run_id", "TEXT")
            self._ensure_sqlite_column(conn, "window_metrics", "detection_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_sqlite_column(conn, "window_features", "run_id", "TEXT")
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
                (window_key, run_id, window_start, window_end, total_records, threat_score, detection_count, attack_predicted,
                 model_available, is_anomaly, anomaly_score, anomaly_percentile, summary_json, saved_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics.get("window_key"),
                    metrics.get("run_id"),
                    metrics.get("window_start"),
                    metrics.get("window_end"),
                    int(metrics.get("total_records", 0)),
                    int(metrics.get("threat_score", 0)),
                    int(metrics.get("detection_count", 0)),
                    int(bool(metrics.get("attack_predicted", False))),
                    int(bool(metrics.get("model_available", False))),
                    int(bool(metrics.get("is_anomaly", False))),
                    float(metrics.get("anomaly_score", 0.0)),
                    float(metrics.get("anomaly_percentile", 0.0)),
                    json.dumps(metrics, ensure_ascii=True),
                    metrics.get("saved_at_utc") or datetime.utcnow().isoformat(),
                ),
            )
            if _should_train_on_window(metrics):
                feature_columns = ", ".join(NUMERIC_FEATURE_COLUMNS)
                feature_placeholders = ", ".join("?" for _ in NUMERIC_FEATURE_COLUMNS)
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO window_features
                    (window_key, run_id, {feature_columns}, saved_at_utc)
                    VALUES (?, ?, {feature_placeholders}, ?)
                    """,
                    (
                        metrics.get("window_key"),
                        metrics.get("run_id"),
                        *[float(metrics.get(column, 0.0) or 0.0) for column in NUMERIC_FEATURE_COLUMNS],
                        metrics.get("saved_at_utc") or datetime.utcnow().isoformat(),
                    ),
                )
            else:
                conn.execute(
                    "DELETE FROM window_features WHERE window_key = ?",
                    (metrics.get("window_key"),),
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
                WHERE total_records > 0
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

    def export_raw_logs(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT log_id, payload
                FROM raw_logs
                ORDER BY ingested_at ASC
                """
            ).fetchall()
        return [json.loads(str(row["payload"])) for row in rows]

    def export_ingest_runs(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, status, started_at_utc, ended_at_utc, duration_seconds,
                       window_start, window_end, total_pages_expected, total_pages_fetched,
                       total_records_info, total_records_fetched, error_message
                FROM ingest_runs
                ORDER BY started_at_utc ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def export_alerts(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT alert_id, run_id, detected_at_utc, alert_type, severity, payload
                FROM alerts_events
                ORDER BY detected_at_utc ASC
                """
            ).fetchall()
        alerts: List[Dict[str, Any]] = []
        for row in rows:
            alert = dict(row)
            payload = alert.get("payload")
            if isinstance(payload, str):
                alert["payload"] = json.loads(payload)
            alerts.append(alert)
        return alerts

    def export_window_metrics(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT summary_json
                FROM window_metrics
                ORDER BY saved_at_utc ASC
                """
            ).fetchall()
        return [json.loads(str(row["summary_json"])) for row in rows]

    def delete_raw_logs(self, log_ids: List[str]) -> int:
        return self._delete_by_ids("raw_logs", "log_id", log_ids)

    def delete_ingest_runs(self, run_ids: List[str]) -> int:
        return self._delete_by_ids("ingest_runs", "run_id", run_ids)

    def delete_alerts(self, alert_ids: List[str]) -> int:
        return self._delete_by_ids("alerts_events", "alert_id", alert_ids)

    def delete_window_metrics(self, window_keys: List[str]) -> int:
        deleted = self._delete_by_ids("window_metrics", "window_key", window_keys)
        if window_keys:
            self._delete_by_ids("window_features", "window_key", window_keys)
        return deleted

    def get_pending_counts(self) -> Dict[str, int]:
        with self._connect() as conn:
            return {
                "raw_logs": int(conn.execute("SELECT COUNT(*) FROM raw_logs").fetchone()[0]),
                "ingest_runs": int(conn.execute("SELECT COUNT(*) FROM ingest_runs").fetchone()[0]),
                "alerts_events": int(conn.execute("SELECT COUNT(*) FROM alerts_events").fetchone()[0]),
                "window_metrics": int(conn.execute("SELECT COUNT(*) FROM window_metrics").fetchone()[0]),
            }

    @staticmethod
    def _fallback_id(record: Dict[str, Any]) -> str:
        payload = json.dumps(record, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _ensure_sqlite_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
        columns = {
            str(row["name"]).lower()
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name.lower() not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def _delete_by_ids(self, table_name: str, column_name: str, ids: List[str]) -> int:
        if not ids:
            return 0

        placeholders = ", ".join("?" for _ in ids)
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {table_name} WHERE {column_name} IN ({placeholders})",
                tuple(ids),
            )
            conn.commit()
            return cursor.rowcount if cursor.rowcount is not None else 0


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
                    RUN_ID NVARCHAR(64),
                    WINDOW_START NVARCHAR(64),
                    WINDOW_END NVARCHAR(64),
                    TOTAL_RECORDS INTEGER,
                    THREAT_SCORE INTEGER,
                    DETECTION_COUNT INTEGER,
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
                    RUN_ID NVARCHAR(64),
                    TOTAL_RECORDS DOUBLE,
                    SYSTEM_LOG_COUNT DOUBLE,
                    LLM_LOG_COUNT DOUBLE,
                    ERROR_COUNT DOUBLE,
                    SECURITY_COUNT DOUBLE,
                    WARNING_COUNT DOUBLE,
                    AUDIT_COUNT DOUBLE,
                    DEBUG_COUNT DOUBLE,
                    UNIQUE_CLIENT_IPS DOUBLE,
                    UNIQUE_SERVICES DOUBLE,
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

            self._ensure_hana_column(cursor, schema, "WINDOW_METRICS", "RUN_ID", "NVARCHAR(64)")
            self._ensure_hana_column(cursor, schema, "WINDOW_METRICS", "DETECTION_COUNT", "INTEGER")
            self._ensure_hana_column(cursor, schema, "WINDOW_FEATURES", "RUN_ID", "NVARCHAR(64)")
            for column in NUMERIC_FEATURE_COLUMNS:
                self._ensure_hana_column(cursor, schema, "WINDOW_FEATURES", column.upper(), "DOUBLE")

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
                '(WINDOW_KEY, RUN_ID, WINDOW_START, WINDOW_END, TOTAL_RECORDS, THREAT_SCORE, DETECTION_COUNT, ATTACK_PREDICTED, '
                'MODEL_AVAILABLE, IS_ANOMALY, ANOMALY_SCORE, ANOMALY_PERCENTILE, SUMMARY_JSON, SAVED_AT_UTC) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) WITH PRIMARY KEY'
            )
            cursor.execute(
                statement,
                (
                    metrics.get("window_key"),
                    metrics.get("run_id"),
                    metrics.get("window_start"),
                    metrics.get("window_end"),
                    int(metrics.get("total_records", 0)),
                    int(metrics.get("threat_score", 0)),
                    int(metrics.get("detection_count", 0)),
                    int(bool(metrics.get("attack_predicted", False))),
                    int(bool(metrics.get("model_available", False))),
                    int(bool(metrics.get("is_anomaly", False))),
                    float(metrics.get("anomaly_score", 0.0)),
                    float(metrics.get("anomaly_percentile", 0.0)),
                    json.dumps(metrics, ensure_ascii=True),
                    metrics.get("saved_at_utc") or datetime.utcnow().isoformat(),
                ),
            )
            if _should_train_on_window(metrics):
                feature_columns = [column.upper() for column in NUMERIC_FEATURE_COLUMNS]
                feature_column_sql = ", ".join(feature_columns)
                feature_placeholders = ", ".join("?" for _ in feature_columns)
                feature_statement = (
                    f'UPSERT "{schema}"."WINDOW_FEATURES" '
                    f'(WINDOW_KEY, RUN_ID, {feature_column_sql}, SAVED_AT_UTC) '
                    f'VALUES (?, ?, {feature_placeholders}, ?) '
                    'WITH PRIMARY KEY'
                )
                cursor.execute(
                    feature_statement,
                    (
                        metrics.get("window_key"),
                        metrics.get("run_id"),
                        *[float(metrics.get(column, 0.0) or 0.0) for column in NUMERIC_FEATURE_COLUMNS],
                        metrics.get("saved_at_utc") or datetime.utcnow().isoformat(),
                    ),
                )
            else:
                cursor.execute(
                    f'DELETE FROM "{schema}"."WINDOW_FEATURES" WHERE WINDOW_KEY = ?',
                    (metrics.get("window_key"),),
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
                WHERE TOTAL_RECORDS > 0
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

    @staticmethod
    def _ensure_hana_column(cursor: Any, schema: str, table_name: str, column_name: str, column_type: str) -> None:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM SYS.TABLE_COLUMNS
            WHERE SCHEMA_NAME = ?
              AND TABLE_NAME = ?
              AND COLUMN_NAME = ?
            """,
            (schema, table_name.upper(), column_name.upper()),
        )
        exists = int(cursor.fetchone()[0] or 0) > 0
        if not exists:
            cursor.execute(f'ALTER TABLE "{schema}"."{table_name}" ADD ("{column_name}" {column_type})')


class ResilientStore(BaseStore):
    def __init__(self, primary: BaseStore, fallback: SqliteStore) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_available = False
        self.last_primary_error: str | None = None
        self.last_fallback_write_utc: str | None = None
        self.last_fallback_sync_utc: str | None = None
        self.last_fallback_sync_result: Dict[str, Any] | None = None

    def ensure_schema(self) -> None:
        self.fallback.ensure_schema()
        try:
            self.primary.ensure_schema()
            self.primary_available = True
            self.last_primary_error = None
        except Exception as exc:
            self.primary_available = False
            self.last_primary_error = str(exc)

    def upsert_raw_logs(self, records: List[Dict[str, Any]]) -> int:
        return self._write_with_fallback("upsert_raw_logs", records)

    def bulk_upsert_raw_logs(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        return self._write_with_fallback("bulk_upsert_raw_logs", records, batch_size=batch_size)

    def insert_ingest_run(self, ingest_run: Dict[str, Any]) -> None:
        self._write_with_fallback("insert_ingest_run", ingest_run)

    def insert_alerts(self, alerts: List[Dict[str, Any]]) -> int:
        return self._write_with_fallback("insert_alerts", alerts)

    def get_last_run(self) -> Optional[Dict[str, Any]]:
        return self._read_with_fallback("get_last_run")

    def upsert_window_metrics(self, metrics: Dict[str, Any]) -> None:
        self._write_with_fallback("upsert_window_metrics", metrics)

    def bulk_upsert_window_metrics(self, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        return self._write_with_fallback("bulk_upsert_window_metrics", records, batch_size=batch_size)

    def get_recent_window_metrics(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._read_with_fallback("get_recent_window_metrics", limit=limit)

    def get_recent_alerts(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._read_with_fallback("get_recent_alerts", limit=limit)

    def get_recent_ingest_runs(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._read_with_fallback("get_recent_ingest_runs", limit=limit)

    def get_dashboard_summary(self, time_window_hours: int = 24) -> Dict[str, Any]:
        return self._read_with_fallback("get_dashboard_summary", time_window_hours=time_window_hours)

    def get_recent_window_features(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._read_with_fallback("get_recent_window_features", limit=limit)

    def get_latest_window_metrics(self) -> Optional[Dict[str, Any]]:
        return self._read_with_fallback("get_latest_window_metrics")

    def call_cleanup_procedure(self, retention_days: int = 90) -> Dict[str, Any]:
        primary_result: Dict[str, Any] | None = None
        primary_error: str | None = None
        try:
            primary_result = self.primary.call_cleanup_procedure(retention_days=retention_days)
            self.primary_available = True
            self.last_primary_error = None
        except Exception as exc:
            self.primary_available = False
            self.last_primary_error = str(exc)
            primary_error = str(exc)
        fallback_result = self.fallback.call_cleanup_procedure(retention_days=retention_days)
        return {
            "status": "ok" if primary_error is None else "fallback_only",
            "primary": primary_result,
            "primary_error": primary_error,
            "fallback": fallback_result,
        }

    def sync_fallback_to_primary(self) -> Dict[str, Any]:
        self.primary.ensure_schema()

        synced_counts = {
            "raw_logs": 0,
            "ingest_runs": 0,
            "alerts_events": 0,
            "window_metrics": 0,
        }

        ingest_runs = self.fallback.export_ingest_runs()
        for ingest_run in ingest_runs:
            self.primary.insert_ingest_run(ingest_run)
        synced_counts["ingest_runs"] = self.fallback.delete_ingest_runs(
            [str(row.get("run_id")) for row in ingest_runs if row.get("run_id")]
        )

        raw_logs = self.fallback.export_raw_logs()
        synced_counts["raw_logs"] = self.primary.bulk_upsert_raw_logs(raw_logs, batch_size=1000)
        self.fallback.delete_raw_logs(
            [str(row.get("_id") or SqliteStore._fallback_id(row)) for row in raw_logs]
        )

        window_metrics = self.fallback.export_window_metrics()
        synced_counts["window_metrics"] = self.primary.bulk_upsert_window_metrics(window_metrics, batch_size=250)
        self.fallback.delete_window_metrics(
            [str(row.get("window_key")) for row in window_metrics if row.get("window_key")]
        )

        alerts = self.fallback.export_alerts()
        synced_counts["alerts_events"] = self.primary.insert_alerts(alerts)
        self.fallback.delete_alerts(
            [str(row.get("alert_id")) for row in alerts if row.get("alert_id")]
        )

        self.primary_available = True
        self.last_primary_error = None

        return {
            "status": "ok",
            "synced_counts": synced_counts,
            "pending_counts": self.fallback.get_pending_counts(),
        }

    def get_fallback_status(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "primary_backend": self.primary.__class__.__name__,
            "fallback_backend": self.fallback.__class__.__name__,
            "primary_available": self.primary_available,
            "last_primary_error": self.last_primary_error,
            "last_fallback_write_utc": self.last_fallback_write_utc,
            "last_fallback_sync_utc": self.last_fallback_sync_utc,
            "last_fallback_sync_result": self.last_fallback_sync_result,
            "pending_counts": self.fallback.get_pending_counts(),
        }

    def _read_with_fallback(self, method_name: str, **kwargs: Any) -> Any:
        try:
            result = getattr(self.primary, method_name)(**kwargs)
            self.primary_available = True
            self.last_primary_error = None
            if self._sync_fallback_if_pending():
                result = getattr(self.primary, method_name)(**kwargs)
            return result
        except Exception as exc:
            self.primary_available = False
            self.last_primary_error = str(exc)
            return getattr(self.fallback, method_name)(**kwargs)

    def _write_with_fallback(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            result = getattr(self.primary, method_name)(*args, **kwargs)
            self.primary_available = True
            self.last_primary_error = None
            self._sync_fallback_if_pending()
            return result
        except Exception as exc:
            self.primary_available = False
            self.last_primary_error = str(exc)
            self.last_fallback_write_utc = datetime.now().isoformat()
            return getattr(self.fallback, method_name)(*args, **kwargs)

    def _sync_fallback_if_pending(self) -> bool:
        pending_counts = self.fallback.get_pending_counts()
        if not any(pending_counts.values()):
            return False

        result = self.sync_fallback_to_primary()
        self.last_fallback_sync_utc = datetime.now().isoformat()
        self.last_fallback_sync_result = result
        return True


def create_store(settings: Settings) -> BaseStore:
    if settings.storage_backend == "hana":
        return ResilientStore(
            primary=HanaStore(settings),
            fallback=SqliteStore(settings.sqlite_path),
        )
    return SqliteStore(settings.sqlite_path)


def _should_train_on_window(metrics: Dict[str, Any]) -> bool:
    if int(metrics.get("total_records", 0) or 0) <= 0:
        return False
    return str(metrics.get("anomaly_reason", "")) not in {
        "empty_window",
        "possible_incomplete_window",
        "llm_activity_drop",
        "llm_quality_degradation",
        "system_activity_drop",
    }
