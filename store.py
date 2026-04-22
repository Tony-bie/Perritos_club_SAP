from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import Settings


class BaseStore(ABC):
    @abstractmethod
    def ensure_schema(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_raw_logs(self, records: List[Dict[str, Any]]) -> int:
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_logs_log_ts ON raw_logs(log_ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON ingest_runs(started_at_utc)")
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
            encrypt="true",
            sslValidateCertificate="true",
        )

    def ensure_schema(self) -> None:
        schema = self.settings.hana_schema
        with self._connect() as conn:
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
        with self._connect() as conn:
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

    def insert_ingest_run(self, ingest_run: Dict[str, Any]) -> None:
        schema = self.settings.hana_schema
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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


def create_store(settings: Settings) -> BaseStore:
    if settings.storage_backend == "hana":
        return HanaStore(settings)
    return SqliteStore(settings.sqlite_path)
