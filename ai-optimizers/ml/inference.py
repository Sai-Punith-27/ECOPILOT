"""
inference.py
=============
Loads the trained model (artifacts/model.joblib + metrics.json) once and
exposes a single function, predict_energy(), for the FastAPI backend to
call. Designed so a missing/corrupt model file or bad input NEVER raises
an unhandled exception into the caller -- it always returns a dict with
`model_available` set correctly, so the backend route (and, downstream,
the deterministic optimizer) can carry on regardless.
"""

import os
from typing import Dict, Optional

import joblib

from model import engineer_features_from_dict

_DEFAULT_ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "artifacts")

_model = None
_metrics: Optional[Dict] = None
_load_error: Optional[str] = None
_loaded_from: Optional[str] = None


def _load(artifact_dir: str = _DEFAULT_ARTIFACT_DIR) -> None:
    """Load model + metrics into module-level cache. Safe to call more than
    once; only re-loads if not already loaded or if the directory changes."""
    global _model, _metrics, _load_error, _loaded_from

    if _model is not None and _loaded_from == artifact_dir:
        return

    model_path = os.path.join(artifact_dir, "model.joblib")
    metrics_path = os.path.join(artifact_dir, "metrics.json")

    try:
        import json
        _model = joblib.load(model_path)
        with open(metrics_path) as f:
            _metrics = json.load(f)
        _load_error = None
        _loaded_from = artifact_dir
    except Exception as exc:  # noqa: BLE001 - intentionally broad: any load
        # failure (missing file, corrupt pickle, version mismatch) must
        # degrade gracefully, never crash the backend.
        _model = None
        _metrics = None
        _load_error = f"{type(exc).__name__}: {exc}"
        _loaded_from = None


def is_model_available(artifact_dir: str = _DEFAULT_ARTIFACT_DIR) -> bool:
    _load(artifact_dir)
    return _model is not None


def predict_energy(payload: Dict, artifact_dir: str = _DEFAULT_ARTIFACT_DIR) -> Dict:
    """
    Predict near-term household energy consumption (Wh) from a
    telemetry-shaped payload. See model.engineer_features_from_dict for the
    required keys.

    Always returns a dict shaped like:
        {
          "model_available": bool,
          "predicted_energy_wh": float | None,
          "confidence_rmse": float | None,
          "model_version": str | None,
          "error": str | None,
        }

    Never raises -- any failure (model not trained yet, bad input, etc.)
    is captured in `error` with model_available=False, so the caller can
    fall back to deterministic-only behaviour.
    """
    _load(artifact_dir)

    if _model is None:
        return {
            "model_available": False,
            "predicted_energy_wh": None,
            "confidence_rmse": None,
            "model_version": None,
            "error": _load_error or "Model not loaded",
        }

    try:
        features = engineer_features_from_dict(payload)
        prediction = float(_model.predict(features)[0])
        # Energy can't be physically negative; clip defensively since a
        # linear model can extrapolate below zero for unusual inputs.
        prediction = max(0.0, prediction)
        return {
            "model_available": True,
            "predicted_energy_wh": round(prediction, 2),
            "confidence_rmse": round(_metrics["selected_model_test_metrics"]["rmse"], 2),
            "model_version": _metrics.get("model_version"),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - bad/incomplete input must
        # degrade gracefully too, not 500 the request.
        return {
            "model_available": False,
            "predicted_energy_wh": None,
            "confidence_rmse": None,
            "model_version": _metrics.get("model_version") if _metrics else None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def get_metrics(artifact_dir: str = _DEFAULT_ARTIFACT_DIR) -> Optional[Dict]:
    """Expose full training metrics (for a diagnostics/about page if wanted)."""
    _load(artifact_dir)
    return _metrics
