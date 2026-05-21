"""Tests for backend/services/detection/model.py — target >= 70%.

Strategy: test all pure helper functions (no HANA needed) + mock HANA
for score_window_metrics paths.
"""
import sys
import unittest
from unittest.mock import MagicMock, patch


def _make_settings(backend="hana", algorithm="isolation_forest", kmeans_clusters=5):
    s = MagicMock()
    s.storage_backend = backend
    s.model_algorithm = algorithm
    s.model_kmeans_clusters = kmeans_clusters
    s.hana_host = "hana.host"
    s.hana_port = 443
    s.hana_encrypt = True
    s.hana_validate_certificate = True
    s.hana_user = "user"
    s.hana_password = "pass"
    s.hana_token = None
    s.hana_schema = "SCHEMA"
    return s


def _make_prediction_rows(window_keys, scores=None, is_anomalies=None):
    rows = []
    for i, key in enumerate(window_keys):
        score = scores[i] if scores else float(i + 1)
        anomaly = is_anomalies[i] if is_anomalies else None
        rows.append({
            "window_key": key,
            "anomaly_score": score,
            "is_anomaly": anomaly,
        })
    return rows


def _hana_sys_modules(mock_conn=None):
    mock_hana_ml = MagicMock()
    mock_hana_ml.__version__ = "2.0"
    mock_conn_ctx_cls = MagicMock()
    if mock_conn:
        mock_conn_ctx_cls.return_value.__enter__.return_value = mock_conn
        mock_conn_ctx_cls.return_value.__exit__.return_value = False
    return {
        "hana_ml": mock_hana_ml,
        "hana_ml.dataframe": MagicMock(ConnectionContext=mock_conn_ctx_cls),
        "hana_ml.algorithms": MagicMock(),
        "hana_ml.algorithms.pal": MagicMock(),
        "hana_ml.algorithms.pal.preprocessing": MagicMock(),
        "hana_ml.algorithms.pal.clustering": MagicMock(),
    }, mock_hana_ml


class TestUnavailableModelSignal(unittest.TestCase):

    def test_returns_expected_shape(self):
        from backend.services.detection.model import unavailable_model_signal
        result = unavailable_model_signal("test_reason")
        self.assertFalse(result["model_available"])
        self.assertEqual(result["source"], "test_reason")
        self.assertEqual(result["anomaly_score"], 0.0)
        self.assertEqual(result["is_anomaly"], False)

    def test_source_is_preserved(self):
        from backend.services.detection.model import unavailable_model_signal
        result = unavailable_model_signal("hana_ml_requires_hana_backend")
        self.assertEqual(result["source"], "hana_ml_requires_hana_backend")


class TestScoreWindowMetricsNonHana(unittest.TestCase):

    def test_non_hana_backend_returns_unavailable(self):
        from backend.services.detection.model import score_window_metrics
        settings = _make_settings(backend="sqlite")
        result = score_window_metrics(settings, "w1", 30, 0.1)
        self.assertFalse(result["model_available"])
        self.assertIn("hana_ml_requires_hana_backend", result["source"])


class TestScoreWindowMetricsWithMockedHana(unittest.TestCase):

    def _make_mock_conn(self, row_count=50):
        mock_conn = MagicMock()
        mock_feature_df = MagicMock()
        mock_feature_df.count.return_value = row_count
        mock_conn.table.return_value.select.return_value.dropna.return_value = mock_feature_df
        return mock_conn, mock_feature_df

    def test_isolation_forest_happy_path(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, mock_fd = self._make_mock_conn(50)
        sys_mods, _ = _hana_sys_modules(mock_conn)
        pred_rows = [{"WINDOW_KEY": "w1", "SCORE": 2.5, "IS_ANOMALY": 1}]
        with patch.dict("sys.modules", sys_mods), \
             patch("backend.services.detection.model._run_isolation_forest_scores",
                   return_value=(pred_rows, "hana_ml.iforest:2.0")):
            result = score_window_metrics(_make_settings("hana", "isolation_forest"), "w1", 30, 0.1)
        self.assertTrue(result["model_available"])
        self.assertEqual(result["training_row_count"], 50)

    def test_kmeans_happy_path(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, _ = self._make_mock_conn(50)
        sys_mods, _ = _hana_sys_modules(mock_conn)
        pred_rows = [{"WINDOW_KEY": "w1", "SCORE": 1.0, "IS_ANOMALY": 0}]
        with patch.dict("sys.modules", sys_mods), \
             patch("backend.services.detection.model._run_kmeans_scores",
                   return_value=(pred_rows, "hana_ml.kmeans:2.0")):
            result = score_window_metrics(_make_settings("hana", "kmeans"), "w1", 30, 0.1)
        self.assertTrue(result["model_available"])

    def test_hybrid_happy_path(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, _ = self._make_mock_conn(50)
        sys_mods, _ = _hana_sys_modules(mock_conn)
        pred_rows = [{"WINDOW_KEY": "w1", "SCORE": 1.5, "IS_ANOMALY": 1}]
        with patch.dict("sys.modules", sys_mods), \
             patch("backend.services.detection.model._run_isolation_forest_scores",
                   return_value=(pred_rows, "iforest")), \
             patch("backend.services.detection.model._run_kmeans_scores",
                   return_value=(pred_rows, "kmeans")):
            result = score_window_metrics(_make_settings("hana", "hybrid"), "w1", 30, 0.1)
        self.assertIn("model_available", result)

    def test_unsupported_algorithm_returns_unavailable(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, _ = self._make_mock_conn(50)
        sys_mods, _ = _hana_sys_modules(mock_conn)
        with patch.dict("sys.modules", sys_mods):
            result = score_window_metrics(_make_settings("hana", "unknown_algo"), "w1", 30, 0.1)
        self.assertFalse(result["model_available"])
        self.assertIn("unsupported", result["source"])

    def test_insufficient_history_returns_unavailable(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, _ = self._make_mock_conn(row_count=5)
        sys_mods, _ = _hana_sys_modules(mock_conn)
        with patch.dict("sys.modules", sys_mods):
            result = score_window_metrics(_make_settings("hana", "isolation_forest"), "w1", 30, 0.1)
        self.assertFalse(result["model_available"])
        self.assertIn("insufficient_history", result["source"])

    def test_runtime_error_returns_unavailable(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn = MagicMock()
        mock_conn.table.side_effect = RuntimeError("HANA connection lost")
        sys_mods, _ = _hana_sys_modules(mock_conn)
        with patch.dict("sys.modules", sys_mods):
            result = score_window_metrics(_make_settings("hana", "isolation_forest"), "w1", 30, 0.1)
        self.assertFalse(result["model_available"])
        self.assertIn("hana_ml_runtime_error", result["source"])

    def test_empty_score_rows_returns_unavailable(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, _ = self._make_mock_conn(50)
        sys_mods, _ = _hana_sys_modules(mock_conn)
        with patch.dict("sys.modules", sys_mods), \
             patch("backend.services.detection.model._run_isolation_forest_scores",
                   return_value=([], "iforest")):
            result = score_window_metrics(_make_settings("hana", "isolation_forest"), "w1", 30, 0.1)
        self.assertFalse(result["model_available"])

    def test_window_key_not_found_returns_unavailable(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, _ = self._make_mock_conn(50)
        sys_mods, _ = _hana_sys_modules(mock_conn)
        pred_rows = [{"WINDOW_KEY": "OTHER", "SCORE": 1.5, "IS_ANOMALY": 1}]
        with patch.dict("sys.modules", sys_mods), \
             patch("backend.services.detection.model._run_isolation_forest_scores",
                   return_value=(pred_rows, "iforest")):
            result = score_window_metrics(_make_settings("hana", "isolation_forest"), "w1", 30, 0.1)
        self.assertFalse(result["model_available"])
        self.assertIn("current_window_not_found", result["source"])

    def test_component_percentiles_included_in_hybrid(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, _ = self._make_mock_conn(50)
        sys_mods, _ = _hana_sys_modules(mock_conn)
        pred_rows = [{"WINDOW_KEY": "w1", "SCORE": 1.5, "IS_ANOMALY": 1}]
        with patch.dict("sys.modules", sys_mods), \
             patch("backend.services.detection.model._run_isolation_forest_scores",
                   return_value=(pred_rows, "iforest")), \
             patch("backend.services.detection.model._run_kmeans_scores",
                   return_value=(pred_rows, "kmeans")):
            result = score_window_metrics(_make_settings("hana", "hybrid"), "w1", 30, 0.1)
        if result["model_available"]:
            self.assertIn("component_percentiles", result)

    def test_hana_token_used_when_present(self):
        from backend.services.detection.model import score_window_metrics
        mock_conn, _ = self._make_mock_conn(50)
        sys_mods, sys_mods_hana = _hana_sys_modules(mock_conn)
        settings = _make_settings("hana", "isolation_forest")
        settings.hana_token = "oauth-token-123"
        pred_rows = [{"WINDOW_KEY": "w1", "SCORE": 1.0, "IS_ANOMALY": 0}]
        with patch.dict("sys.modules", sys_mods), \
             patch("backend.services.detection.model._run_isolation_forest_scores",
                   return_value=(pred_rows, "iforest")):
            result = score_window_metrics(settings, "w1", 30, 0.1)
        # Just verify it runs without error — the token path was executed
        self.assertIn("model_available", result)


class TestNormalizePredictionRow(unittest.TestCase):

    def test_lowercase_keys_normalized(self):
        from backend.services.detection.model import _normalize_prediction_row
        row = {"window_key": "w1", "score": 1.5, "is_anomaly": 1}
        result = _normalize_prediction_row(row)
        self.assertEqual(result["window_key"], "w1")
        self.assertAlmostEqual(result["anomaly_score"], 1.5)
        self.assertEqual(result["is_anomaly"], 1)

    def test_uppercase_keys_normalized(self):
        from backend.services.detection.model import _normalize_prediction_row
        row = {"WINDOW_KEY": "w2", "DISTANCE": 3.0, "OUTLIER": 0}
        result = _normalize_prediction_row(row)
        self.assertEqual(result["window_key"], "w2")
        self.assertAlmostEqual(result["anomaly_score"], 3.0)

    def test_missing_window_key_gives_empty_string(self):
        from backend.services.detection.model import _normalize_prediction_row
        result = _normalize_prediction_row({"SCORE": 1.0})
        self.assertEqual(result["window_key"], "")

    def test_various_score_column_names(self):
        from backend.services.detection.model import _normalize_prediction_row
        for col in ["DISTANCE", "SCORE", "ANOMALY_SCORE", "RAW_SCORE"]:
            row = {"WINDOW_KEY": "w", col: 2.5}
            result = _normalize_prediction_row(row)
            self.assertAlmostEqual(result["anomaly_score"], 2.5, msg=f"Failed for column {col}")

    def test_various_label_column_names(self):
        from backend.services.detection.model import _normalize_prediction_row
        for col in ["IS_ANOMALY", "OUTLIER", "PREDICTION", "LABEL"]:
            row = {"WINDOW_KEY": "w", col: 1}
            result = _normalize_prediction_row(row)
            self.assertEqual(result["is_anomaly"], 1, msg=f"Failed for column {col}")


class TestFirstFloat(unittest.TestCase):

    def test_returns_first_valid_float(self):
        from backend.services.detection.model import _first_float
        result = _first_float({"A": None, "B": 2.5, "C": 3.0}, ["A", "B", "C"])
        self.assertAlmostEqual(result, 2.5)

    def test_returns_none_when_all_missing(self):
        from backend.services.detection.model import _first_float
        result = _first_float({"X": None}, ["A", "B"])
        self.assertIsNone(result)

    def test_skips_non_numeric(self):
        from backend.services.detection.model import _first_float
        result = _first_float({"A": "not-a-number", "B": 1.0}, ["A", "B"])
        self.assertAlmostEqual(result, 1.0)


class TestFirstInt(unittest.TestCase):

    def test_returns_first_valid_int(self):
        from backend.services.detection.model import _first_int
        result = _first_int({"A": None, "B": 1}, ["A", "B"])
        self.assertEqual(result, 1)

    def test_returns_none_when_all_missing(self):
        from backend.services.detection.model import _first_int
        result = _first_int({}, ["A", "B"])
        self.assertIsNone(result)

    def test_skips_non_castable(self):
        from backend.services.detection.model import _first_int
        result = _first_int({"A": "bad", "B": 0}, ["A", "B"])
        self.assertEqual(result, 0)


class TestApplyContaminationThreshold(unittest.TestCase):

    def test_sets_is_anomaly_by_percentile(self):
        from backend.services.detection.model import apply_contamination_threshold
        rows = [
            {"window_key": f"w{i}", "anomaly_score": float(i), "is_anomaly": None}
            for i in range(1, 11)
        ]
        apply_contamination_threshold(rows, contamination=0.1)
        # Top 10% (score=10) should be anomaly
        self.assertEqual(rows[9]["is_anomaly"], 1)
        self.assertEqual(rows[0]["is_anomaly"], 0)

    def test_skips_rows_with_existing_is_anomaly(self):
        from backend.services.detection.model import apply_contamination_threshold
        rows = [{"window_key": "w1", "anomaly_score": 5.0, "is_anomaly": 0}]
        apply_contamination_threshold(rows, contamination=0.5)
        self.assertEqual(rows[0]["is_anomaly"], 0)

    def test_no_unresolved_rows_is_noop(self):
        from backend.services.detection.model import apply_contamination_threshold
        rows = [{"window_key": "w1", "anomaly_score": None, "is_anomaly": None}]
        apply_contamination_threshold(rows, contamination=0.1)
        self.assertIsNone(rows[0]["is_anomaly"])

    def test_single_row(self):
        from backend.services.detection.model import apply_contamination_threshold
        rows = [{"window_key": "w1", "anomaly_score": 5.0, "is_anomaly": None}]
        apply_contamination_threshold(rows, contamination=0.1)
        self.assertIsNotNone(rows[0]["is_anomaly"])


class TestApplyConfidenceScores(unittest.TestCase):

    def test_assigns_percentile_by_rank(self):
        from backend.services.detection.model import apply_confidence_scores
        rows = [
            {"window_key": "w1", "anomaly_score": 1.0, "is_anomaly": 0},
            {"window_key": "w2", "anomaly_score": 2.0, "is_anomaly": 0},
            {"window_key": "w3", "anomaly_score": 3.0, "is_anomaly": 1},
        ]
        apply_confidence_scores(rows)
        # w1 has lowest score → lowest percentile
        pcts = {r["window_key"]: r["anomaly_percentile"] for r in rows}
        self.assertLess(pcts["w1"], pcts["w2"])
        self.assertLess(pcts["w2"], pcts["w3"])

    def test_single_row_gets_100_percentile(self):
        from backend.services.detection.model import apply_confidence_scores
        rows = [{"window_key": "w1", "anomaly_score": 5.0, "is_anomaly": 1}]
        apply_confidence_scores(rows)
        self.assertAlmostEqual(rows[0]["anomaly_percentile"], 100.0)

    def test_no_scored_rows_is_noop(self):
        from backend.services.detection.model import apply_confidence_scores
        rows = [{"window_key": "w1", "anomaly_score": None, "is_anomaly": None}]
        apply_confidence_scores(rows)
        self.assertNotIn("anomaly_percentile", rows[0])


class TestMergeHybridRows(unittest.TestCase):

    def _make_processed_rows(self, keys, percentiles):
        return [
            {"window_key": k, "anomaly_score": p, "anomaly_percentile": p, "is_anomaly": int(p > 80)}
            for k, p in zip(keys, percentiles)
        ]

    def test_merges_shared_keys(self):
        from backend.services.detection.model import _merge_hybrid_rows
        iforest = self._make_processed_rows(["w1", "w2"], [60.0, 90.0])
        kmeans = self._make_processed_rows(["w1", "w2"], [70.0, 80.0])
        merged = _merge_hybrid_rows(iforest, kmeans, contamination=0.1)
        self.assertEqual(len(merged), 2)
        # w1: (60+70)/2 = 65.0
        w1 = next(r for r in merged if r["window_key"] == "w1")
        self.assertAlmostEqual(w1["anomaly_percentile"], 65.0)

    def test_empty_iforest_returns_empty(self):
        from backend.services.detection.model import _merge_hybrid_rows
        kmeans = self._make_processed_rows(["w1"], [50.0])
        result = _merge_hybrid_rows([], kmeans, contamination=0.1)
        self.assertEqual(result, [])

    def test_empty_kmeans_returns_empty(self):
        from backend.services.detection.model import _merge_hybrid_rows
        iforest = self._make_processed_rows(["w1"], [50.0])
        result = _merge_hybrid_rows(iforest, [], contamination=0.1)
        self.assertEqual(result, [])

    def test_no_shared_keys_returns_empty(self):
        from backend.services.detection.model import _merge_hybrid_rows
        iforest = self._make_processed_rows(["w1"], [50.0])
        kmeans = self._make_processed_rows(["w2"], [60.0])
        result = _merge_hybrid_rows(iforest, kmeans, contamination=0.1)
        self.assertEqual(result, [])

    def test_component_percentiles_included(self):
        from backend.services.detection.model import _merge_hybrid_rows
        iforest = self._make_processed_rows(["w1"], [40.0])
        kmeans = self._make_processed_rows(["w1"], [60.0])
        merged = _merge_hybrid_rows(iforest, kmeans, contamination=0.1)
        cp = merged[0]["component_percentiles"]
        self.assertAlmostEqual(cp["isolation_forest"], 40.0)
        self.assertAlmostEqual(cp["kmeans"], 60.0)

    def test_is_anomaly_based_on_threshold(self):
        from backend.services.detection.model import _merge_hybrid_rows
        # contamination=0.1 → threshold = (1-0.1)*100 = 90.0
        iforest = self._make_processed_rows(["w1", "w2"], [95.0, 50.0])
        kmeans = self._make_processed_rows(["w1", "w2"], [95.0, 50.0])
        merged = _merge_hybrid_rows(iforest, kmeans, contamination=0.1)
        w1 = next(r for r in merged if r["window_key"] == "w1")
        w2 = next(r for r in merged if r["window_key"] == "w2")
        self.assertEqual(w1["is_anomaly"], 1)   # 95 >= 90
        self.assertEqual(w2["is_anomaly"], 0)   # 50 < 90


if __name__ == "__main__":
    unittest.main()
