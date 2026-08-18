"""
test_inference.py
==================
Tests for ai-optimizers/ml/inference.py. Focused on the guarantee that
matters most for production: a missing/broken model NEVER raises into the
caller, it always degrades to model_available=False.

Run from ai-optimizers/ml/:
    python -m pytest tests/test_inference.py -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inference import predict_energy, is_model_available, get_metrics  # noqa: E402

ARTIFACT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "artifacts")

VALID_PAYLOAD = {
    "indoor_temperature": 24.5,
    "indoor_humidity": 48.0,
    "outdoor_temperature": 34.0,
    "outdoor_humidity": 55.0,
    "recent_energy_wh": 80.0,
    "timestamp": "2026-08-18T15:30:00",
}


class TestModelAvailability(unittest.TestCase):
    def test_model_loads_from_trained_artifacts(self):
        # Requires `python train.py` to have been run first (artifacts/ present).
        self.assertTrue(is_model_available(ARTIFACT_DIR))

    def test_missing_artifact_dir_reports_unavailable(self):
        self.assertFalse(is_model_available("/definitely/not/a/real/path"))


class TestPredictEnergy(unittest.TestCase):
    def test_valid_payload_returns_prediction(self):
        result = predict_energy(VALID_PAYLOAD, ARTIFACT_DIR)
        self.assertTrue(result["model_available"])
        self.assertIsNone(result["error"])
        self.assertIsInstance(result["predicted_energy_wh"], float)
        self.assertGreaterEqual(result["predicted_energy_wh"], 0.0)
        self.assertIsInstance(result["confidence_rmse"], float)
        self.assertIsNotNone(result["model_version"])

    def test_prediction_never_negative(self):
        # Extreme/unusual inputs shouldn't produce a physically impossible
        # negative energy prediction (linear models can extrapolate below 0).
        extreme_payload = dict(VALID_PAYLOAD, recent_energy_wh=0.0,
                                indoor_temperature=10.0, outdoor_temperature=5.0)
        result = predict_energy(extreme_payload, ARTIFACT_DIR)
        if result["model_available"]:
            self.assertGreaterEqual(result["predicted_energy_wh"], 0.0)

    def test_missing_required_field_degrades_gracefully(self):
        incomplete = {"indoor_temperature": 24.5, "timestamp": "2026-08-18T15:30:00"}
        result = predict_energy(incomplete, ARTIFACT_DIR)
        self.assertFalse(result["model_available"])
        self.assertIsNone(result["predicted_energy_wh"])
        self.assertIsNotNone(result["error"])

    def test_missing_model_file_degrades_gracefully_not_raises(self):
        # This is the critical guarantee: predict_energy must never raise,
        # even if the model artifact directory doesn't exist at all.
        try:
            result = predict_energy(VALID_PAYLOAD, "/definitely/not/a/real/path")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"predict_energy raised instead of degrading gracefully: {exc}")
        self.assertFalse(result["model_available"])
        self.assertIsNone(result["predicted_energy_wh"])
        self.assertIsNotNone(result["error"])

    def test_result_has_exact_required_keys(self):
        result = predict_energy(VALID_PAYLOAD, ARTIFACT_DIR)
        expected_keys = {
            "model_available", "predicted_energy_wh",
            "confidence_rmse", "model_version", "error",
        }
        self.assertEqual(set(result.keys()), expected_keys)


class TestMetrics(unittest.TestCase):
    def test_metrics_include_disclaimer_and_honest_baseline_comparison(self):
        metrics = get_metrics(ARTIFACT_DIR)
        self.assertIsNotNone(metrics)
        self.assertIn("disclaimer", metrics)
        self.assertIn("naive_baseline_metrics", metrics)
        self.assertIn("Belgian", metrics["disclaimer"])
        # Disclaimer should explicitly say it is NOT validated for India,
        # not merely be silent on the topic.
        self.assertIn("not validated for Indian households", metrics["disclaimer"])

    def test_selected_model_beats_naive_baseline_on_test_set(self):
        # Not a hard architectural requirement, but a useful regression
        # check: if a future retrain makes the model WORSE than the naive
        # baseline, we want a failing test to catch it, not a silently
        # shipped useless model.
        metrics = get_metrics(ARTIFACT_DIR)
        selected_rmse = metrics["selected_model_test_metrics"]["rmse"]
        naive_rmse = metrics["naive_baseline_metrics"]["test"]["rmse"]
        self.assertLess(selected_rmse, naive_rmse)


if __name__ == "__main__":
    unittest.main(verbosity=2)
