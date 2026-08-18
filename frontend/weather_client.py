"""
EcoPilot Frontend: Weather Client
=====================================
Real, free, no-API-key weather lookup via Open-Meteo
(https://open-meteo.com/ -- CC BY 4.0, no signup required).

Used to fill the "outside_temperature" / "ambient_temperature" inputs
that ac_optimizer.py and fridge_anomaly_detector.py need but that the
EcoPilot telemetry schema does not carry (appliances report their own
state, not outdoor conditions).

Falls back to a documented default if the API call fails for any reason
(offline demo environment, rate limit, etc.) so the rest of the app
never breaks because of this.
"""

import requests

DEFAULT_LAT = 12.9716   # Bengaluru, India -- used only as a fallback default location
DEFAULT_LON = 77.5946
FALLBACK_OUTSIDE_TEMP_C = 33.0  # typical hot-season daytime default if the API is unreachable


def get_outside_conditions(lat=DEFAULT_LAT, lon=DEFAULT_LON, timeout=3.0):
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
                return temp, humidity, "live (Open-Meteo)"
    except Exception:
        pass
    return FALLBACK_OUTSIDE_TEMP_C, None, "fallback default (weather API unreachable)"
