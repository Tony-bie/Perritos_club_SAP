"""Tests for HANA ML functions in model.py with mocked hana_ml — target >= 95%."""
import sys
import unittest
from unittest.mock import MagicMock, patch


def _hana_preprocessing_modules(mock_iforest_cls):
    return {
        "hana_ml": MagicMock(__version__="2.0"),
        "hana_ml.algorithms": MagicMock(),
        "hana_ml.algorithms.pal": MagicMock(),
        "hana_ml.algorithms.pal.preprocessing": MagicMock(IsolationForest=mock_iforest_cls),
        "hana_ml.algorithms.pal.clustering": MagicMock(),
    }


def _hana_clustering_modules(mock_kmeans_cls):
    return {
        "hana_ml": MagicMock(__version__="2.0"),
        "hana_ml.algorithms": MagicMock(),
        "hana_ml.algorithms.pal": MagicMock(),
        "hana_ml.algorithms.pal.preprocessing": MagicMock(),
        "hana_ml.algorithms.pal.clustering": MagicMock(KMeans=mock_kmeans_cls),
    }


class TestRunIsolationForestScores(unittest.TestCase):

    def test_returns_prediction_rows_and_source(self):
        from backend.services.detection.model import _run_isolation_forest_scores

        mock_iforest_cls = MagicMock()
        mock_model = MagicMock()
        mock_iforest_cls.return_value = mock_model
        prediction_data = [
            {"WINDOW_KEY": "w1", "SCORE": 1.5, "IS_ANOMALY": 1},
            {"WINDOW_KEY": "w2", "SCORE": 0.3, "IS_ANOMALY": 0},
        ]
        mock_model.predict.return_value.collect.return_value.to_dict.return_value = prediction_data

        feature_df = MagicMock()
        with patch.dict(sys.modules, _hana_preprocessing_modules(mock_iforest_cls)):
            rows, source = _run_isolation_forest_scores(feature_df, ["COL1", "COL2"], "2.0")

        self.assertEqual(rows, prediction_data)
        self.assertIn("isolation_forest", source)
        self.assertIn("2.0", source)

    def test_model_fitted_with_correct_key(self):
        from backend.services.detection.model import _run_isolation_forest_scores

        mock_iforest_cls = MagicMock()
        mock_model = MagicMock()
        mock_iforest_cls.return_value = mock_model
        mock_model.predict.return_value.collect.return_value.to_dict.return_value = []

        feature_df = MagicMock()
        with patch.dict(sys.modules, _hana_preprocessing_modules(mock_iforest_cls)):
            _run_isolation_forest_scores(feature_df, ["F1"], "2.0")

        fit_kwargs = mock_model.fit.call_args[1]
        self.assertEqual(fit_kwargs["key"], "WINDOW_KEY")

    def test_iforest_created_with_expected_params(self):
        from backend.services.detection.model import _run_isolation_forest_scores

        mock_iforest_cls = MagicMock()
        mock_model = MagicMock()
        mock_iforest_cls.return_value = mock_model
        mock_model.predict.return_value.collect.return_value.to_dict.return_value = []

        with patch.dict(sys.modules, _hana_preprocessing_modules(mock_iforest_cls)):
            _run_isolation_forest_scores(MagicMock(), ["F1"], "2.0")

        mock_iforest_cls.assert_called_once_with(random_state=42, thread_ratio=0)


class TestRunKmeansScores(unittest.TestCase):

    def test_returns_prediction_rows_and_source(self):
        from backend.services.detection.model import _run_kmeans_scores

        mock_kmeans_cls = MagicMock()
        mock_model = MagicMock()
        mock_kmeans_cls.return_value = mock_model
        prediction_data = [
            {"WINDOW_KEY": "w1", "DISTANCE": 0.8},
        ]
        mock_model.fit_predict.return_value.collect.return_value.to_dict.return_value = prediction_data

        with patch.dict(sys.modules, _hana_clustering_modules(mock_kmeans_cls)):
            rows, source = _run_kmeans_scores(MagicMock(), ["F1"], clusters=5, row_count=50, hana_ml_version="2.0")

        self.assertEqual(rows, prediction_data)
        self.assertIn("kmeans", source)
        self.assertIn("2.0", source)

    def test_clusters_clamped_to_row_count(self):
        from backend.services.detection.model import _run_kmeans_scores

        mock_kmeans_cls = MagicMock()
        mock_model = MagicMock()
        mock_kmeans_cls.return_value = mock_model
        mock_model.fit_predict.return_value.collect.return_value.to_dict.return_value = []

        with patch.dict(sys.modules, _hana_clustering_modules(mock_kmeans_cls)):
            _, source = _run_kmeans_scores(MagicMock(), ["F1"], clusters=100, row_count=10, hana_ml_version="1.0")

        # Effective clusters should be clamped to min(100, 10) = 10
        self.assertIn("k=10", source)

    def test_clusters_minimum_is_2(self):
        from backend.services.detection.model import _run_kmeans_scores

        mock_kmeans_cls = MagicMock()
        mock_model = MagicMock()
        mock_kmeans_cls.return_value = mock_model
        mock_model.fit_predict.return_value.collect.return_value.to_dict.return_value = []

        with patch.dict(sys.modules, _hana_clustering_modules(mock_kmeans_cls)):
            _, source = _run_kmeans_scores(MagicMock(), ["F1"], clusters=1, row_count=50, hana_ml_version="1.0")

        self.assertIn("k=2", source)

    def test_kmeans_created_with_expected_params(self):
        from backend.services.detection.model import _run_kmeans_scores

        mock_kmeans_cls = MagicMock()
        mock_model = MagicMock()
        mock_kmeans_cls.return_value = mock_model
        mock_model.fit_predict.return_value.collect.return_value.to_dict.return_value = []

        with patch.dict(sys.modules, _hana_clustering_modules(mock_kmeans_cls)):
            _run_kmeans_scores(MagicMock(), ["F1"], clusters=5, row_count=50, hana_ml_version="2.0")

        call_kwargs = mock_kmeans_cls.call_args[1]
        self.assertEqual(call_kwargs.get("init"), "patent")
        self.assertEqual(call_kwargs.get("max_iter"), 100)
        self.assertEqual(call_kwargs.get("distance_level"), "euclidean")


if __name__ == "__main__":
    unittest.main()
