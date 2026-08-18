"""
weather_client.py (backend)
=============================
Small, self-contained outdoor-weather lookup for the backend's ML
prediction route. This intentionally DUPLICATES frontend/weather_client.py
rather than importing across the service boundary: in the deployed
architecture (Streamlit Cloud + Render), frontend and backend are
different processes on different hosts, so they cannot share a Python
import at runtime. Both copies are ~20 lines and call the same free,
no-key Open-Meteo API, so keeping them in sync is low-cost -- this is a
deliberate, documented trade-off, not an oversight.

Falls back to a documented default if the API call fails for any reason,
so the /api/predict route never breaks because of this.
"""

import requests

DEFAULT_LAT = 12.9716   # Bengaluru, India -- used only as a fallback default location
DEFAULT_LON = 77.5946
FALLBACK_OUTSIDE_TEMP_C = 33.0   # typical hot-season daytime default if the API is unreachable
FALLBACK_OUTSIDE_HUMIDITY_PCT = 50.0


def get_outside_conditions(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON, timeout: float = 3.0):
    """Returns (temperature_c, humidity_pct, source_note)."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m",
            },
            timeout=timeout,
        )
        if r.status_code == 200:
            data = r.json()
            current = data.get("current", {})
            temp = current.get("temperature_2m")
            humidity = current.get("relative_humidity_2m")
            if temp is not None:
                return temp, (humidity if humidity is not None else FALLBACK_OUTSIDE_HUMIDITY_PCT), "live (Open-Meteo)"
    except Exception:
        pass
    return FALLBACK_OUTSIDE_TEMP_C, FALLBACK_OUTSIDE_HUMIDITY_PCT, "fallback default (weather API unreachable)"
