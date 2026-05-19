"""Local retraining pipeline that combines feedback labels and DLQ samples."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..core.logging_config import configure_logging
from ..feedback.repo import init_db, list_feedback
from ..ingest.dlq import read_mock_dlq

configure_logging()
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TrainingExample:
	alert_id: str
	amount: float
	label: int
	source: str


def _project_root() -> Path:
	return Path(__file__).resolve().parents[2]


def _normalize_label(value: str | None) -> int:
	if not value:
		return 0
	normalized = value.strip().upper()
	if normalized in {"FP", "FALSE_POSITIVE", "FALSE-POSITIVE", "NEGATIVE", "0"}:
		return 0
	return 1


def _extract_amount(payload: Any) -> float:
	if not isinstance(payload, dict):
		return 0.0
	for key in ("amount", "score", "value"):
		raw = payload.get(key)
		if raw is None:
			continue
		try:
			return float(raw)
		except (TypeError, ValueError):
			continue
	return 0.0


def load_feedback_examples(db_path: str | None = None) -> list[TrainingExample]:
	init_db(db_path or None)
	examples: list[TrainingExample] = []
	for row in list_feedback(limit=1000, path=db_path or None):
		examples.append(
			TrainingExample(
				alert_id=str(row.get("alert_id") or row.get("id") or ""),
				amount=0.0,
				label=_normalize_label(str(row.get("label"))),
				source="feedback",
			)
		)
	return examples


def load_dlq_examples(limit: int = 1000) -> list[TrainingExample]:
	examples: list[TrainingExample] = []
	for item in read_mock_dlq(limit=limit):
		if not isinstance(item, dict):
			continue
		failed = item.get("failed") or {}
		if not isinstance(failed, dict):
			failed = {}
		alert_id = str(failed.get("event_id") or failed.get("alert_id") or failed.get("id") or "")
		if not alert_id:
			continue
		error_text = str(item.get("error") or "")
		label = 1 if error_text else 0
		examples.append(
			TrainingExample(
				alert_id=alert_id,
				amount=_extract_amount(failed),
				label=label,
				source="dlq",
			)
		)
	return examples


def build_dataset(feedback_rows: Iterable[TrainingExample], dlq_rows: Iterable[TrainingExample]) -> tuple[list[list[float]], list[int]]:
	features: list[list[float]] = []
	labels: list[int] = []

	for row in feedback_rows:
		features.append([row.amount, float(len(row.alert_id))])
		labels.append(row.label)

	for row in dlq_rows:
		features.append([row.amount, float(len(row.alert_id))])
		labels.append(row.label)

	return features, labels


def retrain_model(output_path: str | None = None, db_path: str | None = None) -> dict[str, Any]:
	try:
		from joblib import dump
		from sklearn.linear_model import LogisticRegression
	except Exception as exc:
		logger.error("Retrain dependencies missing: %s", exc)
		raise

	feedback_rows = load_feedback_examples(db_path=db_path)
	dlq_rows = load_dlq_examples()
	X, y = build_dataset(feedback_rows, dlq_rows)

	if len(X) < 2 or len(set(y)) < 2:
		logger.warning("Not enough labeled rows to train a classifier")
		return {"trained": False, "rows": len(X)}

	model = LogisticRegression(max_iter=200)
	model.fit(X, y)

	root = _project_root()
	model_path = Path(output_path) if output_path else root / "artifacts" / "models" / "retrain_model.joblib"
	model_path.parent.mkdir(parents=True, exist_ok=True)
	dump(model, model_path)

	payload = {"trained": True, "rows": len(X), "model_path": str(model_path)}
	logger.info("Retrained model saved to %s with %d rows", model_path, len(X))
	return payload


def main() -> None:
	db_path = os.getenv("FEEDBACK_DB")
	output_path = os.getenv("MODEL_OUTPUT") or os.getenv("RETRAIN_MODEL_PATH")
	result = retrain_model(output_path=output_path, db_path=db_path)
	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
