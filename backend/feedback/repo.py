"""Repository layer for feedback storage (sqlite).

Provides simple functions to initialize DB and insert/list feedback rows.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List

from ..core.config import FEEDBACK_DB

DB_PATH = FEEDBACK_DB


def _resolve_path(path: str | None) -> str:
    if path:
        return path
    return DB_PATH


def init_db(path: str | None = None) -> None:
    db_path = _resolve_path(path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id TEXT,
            label TEXT,
            comment TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def insert_feedback(alert_id: str, label: str, comment: str = None, path: str | None = None) -> None:
    db_path = _resolve_path(path)
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT INTO feedback (alert_id, label, comment) VALUES (?, ?, ?)", (alert_id, label, comment))
    conn.commit()
    conn.close()


def list_feedback(limit: int = 100, path: str | None = None) -> List[Dict]:
    db_path = _resolve_path(path)
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, alert_id, label, comment, created_at FROM feedback ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(id=r[0], alert_id=r[1], label=r[2], comment=r[3], created_at=r[4]) for r in rows]
