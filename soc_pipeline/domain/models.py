from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class UtcWindow:
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        return f"{self.start.strftime('%Y%m%dT%H%M%SZ')}_{self.end.strftime('%Y%m%dT%H%M%SZ')}"

    @property
    def label(self) -> str:
        return f"{self.start.isoformat()} -> {self.end.isoformat()}"


@dataclass(frozen=True)
class HanaConfig:
    host: str
    port: int
    user: str
    password: str
    schema: str
    encrypt: bool
    validate_certificate: bool


@dataclass(frozen=True)
class RuntimeConfig:
    base_url: str
    token: str
    timeout_seconds: int
    output_dir: Path
    alert_threshold: int
    poll_interval_seconds: int
    training_min_rows: int
    training_contamination: float
    hana_config: HanaConfig | None
