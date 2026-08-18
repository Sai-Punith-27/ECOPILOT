"""
ml_bridge.py
=============
Locates and imports the ai-optimizers/ml package (ai-optimizers/ml/inference.py)
from inside the backend process.

WHY THIS EXISTS: ai-optimizers/ml lives in a sibling folder to backend/backend
at the repo root (repo/ai-optimizers/ml), not inside the backend/backend
package. The backend needs it purely for read-only inference (loading the
already-trained model.joblib), so we add its folder to sys.path rather than
duplicating the trained model / preprocessing code into the backend package.

Path resolution order:
1. ML_MODULE_DIR env var, if set (e.g. a Docker/Render deployment can point
   this at wherever ai-optimizers/ml ends up inside the image).
2. Otherwise, walk up from this file's location assuming the standard repo
   layout: repo/backend/backend/app/ml_bridge.py -> repo/ai-optimizers/ml.

If neither resolves to a real directory, importing inference fails loudly
here at startup-log time, but predict_energy() itself (in inference.py)
still degrades gracefully at call time -- it never raises into the route.
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))          # .../backend/backend/app
_REPO_ROOT_GUESS = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))  # .../repo
_DEFAULT_ML_DIR = os.path.join(_REPO_ROOT_GUESS, "ai-optimizers", "ml")

ML_MODULE_DIR = os.environ.get("ML_MODULE_DIR", _DEFAULT_ML_DIR)
# Artifacts (model.joblib/metrics.json) live inside ML_MODULE_DIR/artifacts
# by default, but can be pointed elsewhere independently if needed (e.g. a
# mounted volume with a newer retrained model).
ML_ARTIFACT_DIR = os.environ.get("ML_ARTIFACT_DIR", os.path.join(ML_MODULE_DIR, "artifacts"))

if ML_MODULE_DIR not in sys.path:
    sys.path.insert(0, ML_MODULE_DIR)

_import_error = None
try:
    from inference import predict_energy as _predict_energy  # noqa: E402
    from inference import is_model_available as _is_model_available  # noqa: E402
except Exception as exc:  # noqa: BLE001 - see docstring: degrade, don't crash startup
    _import_error = f"{type(exc).__name__}: {exc}"
    _predict_energy = None
    _is_model_available = None


def predict_energy(payload: dict) -> dict:
    """Thin wrapper around ai-optimizers/ml/inference.predict_energy, using
    the resolved ML_ARTIFACT_DIR. Degrades gracefully if the ml package
    itself failed to import (e.g. wrong path in an unusual deployment)."""
    if _predict_energy is None:
        return {
            "model_available": False,
            "predicted_energy_wh": None,
            "confidence_rmse": None,
            "model_version": None,
            "error": f"ML module unavailable: {_import_error}",
        }
    return _predict_energy(payload, artifact_dir=ML_ARTIFACT_DIR)


def is_model_available() -> bool:
    if _is_model_available is None:
        return False
    return _is_model_available(ML_ARTIFACT_DIR)
