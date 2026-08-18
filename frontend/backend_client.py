"""
EcoPilot Frontend: Backend Client
=====================================
Thin HTTP client for the EcoPilot FastAPI backend (../backend/backend),
which stores telemetry posted by ../backend/simulator every ~2 seconds.
"""

import requests
import os

DEFAULT_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://127.0.0.1:8000")
APPLIANCE_IDS = ["ac_01", "fridge_01", "washer_01", "cooler_01"]
APPLIANCE_LABELS = {
    "ac_01": "Air Conditioner",
    "fridge_01": "Refrigerator",
    "washer_01": "Washing Machine",
    "cooler_01": "Desert Cooler",
}


def check_backend_alive(base_url=DEFAULT_BASE_URL, timeout=2.0):
    try:
        r = requests.get(f"{base_url}/api/appliances", timeout=timeout)
        return r.status_code == 200, None
    except requests.exceptions.ConnectionError:
        return False, "Connection refused — is the backend running? (uvicorn app.main:app --port 8000)"
    except requests.exceptions.Timeout:
        return False, "Backend did not respond in time."
    except Exception as e:
        return False, str(e)


def get_latest_telemetry(appliance_id, base_url=DEFAULT_BASE_URL, limit=50, timeout=2.0):
    """Returns a list of reading dicts, newest first, or [] on failure."""
    try:
        r = requests.get(f"{base_url}/api/telemetry/{appliance_id}", params={"limit": limit}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return []
    except Exception:
        return []


def get_all_appliances_latest(base_url=DEFAULT_BASE_URL, limit=50, timeout=2.0):
    return {aid: get_latest_telemetry(aid, base_url=base_url, limit=limit, timeout=timeout)
            for aid in APPLIANCE_IDS}


# Default "unavailable" shape returned whenever the backend can't be
# reached, times out, or returns something unexpected -- callers can
# always safely read result["model_available"] without a try/except.
_PREDICTION_UNAVAILABLE_DEFAULT = {
    "model_available": False,
    "predicted_household_energy_wh": None,
    "confidence_rmse": None,
    "model_version": None,
    "scope_note": None,
    "inputs_used": None,
    "error": None,
}


def get_energy_prediction(appliance_id, base_url=DEFAULT_BASE_URL, timeout=3.0):
    """
    Calls the backend's ML prediction route: GET /api/predict/{appliance_id}.

    Never raises. On any failure (backend down, timeout, unexpected
    response, appliance not found) returns a dict with
    model_available=False and a human-readable `error`, so callers can
    render a plain fallback message instead of special-casing exceptions.
    This mirrors how the deterministic optimizers already handle missing
    data -- ML being unavailable should degrade the SAME way, not crash
    the dashboard.
    """
    result = dict(_PREDICTION_UNAVAILABLE_DEFAULT)
    try:
        r = requests.get(f"{base_url}/api/predict/{appliance_id}", timeout=timeout)
        if r.status_code == 200:
            result.update(r.json())
        elif r.status_code == 404:
            result["error"] = f"Appliance '{appliance_id}' not found on backend."
        else:
            result["error"] = f"Backend returned HTTP {r.status_code} for /api/predict/{appliance_id}."
    except requests.exceptions.ConnectionError:
        result["error"] = "Connection refused — is the backend running?"
    except requests.exceptions.Timeout:
        result["error"] = "Backend did not respond in time for the ML prediction."
    except Exception as e:  # noqa: BLE001 - any other failure must degrade, not crash the dashboard
        result["error"] = str(e)
    return result
