from __future__ import annotations

from pathlib import Path

from backend.feedback.repo import init_db, insert_feedback, list_feedback
from backend.ingest import dlq as dlq_module
from backend.ingest.dlq import append_to_mock_dlq, read_mock_dlq
from backend.ml.retrain import retrain_model


def test_mock_dlq_roundtrip(tmp_path, monkeypatch):
	dlq_path = tmp_path / "mock_dlq.jsonl"
	monkeypatch.setattr(dlq_module, "DLQ_FILE", str(dlq_path))

	append_to_mock_dlq({"failed": {"event_id": "evt_1", "amount": 123}, "error": "boom"})

	items = read_mock_dlq(limit=10)
	assert len(items) == 1
	assert items[0]["failed"]["event_id"] == "evt_1"


def test_feedback_repo_roundtrip(tmp_path):
	db_path = tmp_path / "labels.db"

	init_db(str(db_path))
	insert_feedback("evt_1", "FP", "looks fine", path=str(db_path))

	rows = list_feedback(path=str(db_path))
	assert len(rows) == 1
	assert rows[0]["alert_id"] == "evt_1"
	assert rows[0]["label"] == "FP"


def test_retrain_model_creates_artifact(tmp_path, monkeypatch):
	db_path = tmp_path / "labels.db"
	model_path = tmp_path / "model.joblib"
	dlq_path = tmp_path / "mock_dlq.jsonl"

	monkeypatch.setattr(dlq_module, "DLQ_FILE", str(dlq_path))

	init_db(str(db_path))
	insert_feedback("evt_a", "OK", "positive", path=str(db_path))
	insert_feedback("evt_b", "FP", "negative", path=str(db_path))
	append_to_mock_dlq({"failed": {"event_id": "evt_dlq", "amount": 5000}, "error": "timeout"})

	result = retrain_model(output_path=str(model_path), db_path=str(db_path))

	assert result["rows"] >= 3
	assert result["trained"] is True
	assert Path(result["model_path"]).exists()
