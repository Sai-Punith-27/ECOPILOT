"""
Endpoint for ML-based household energy prediction, using an appliance's
latest telemetry as the local (indoor) signal plus live outdoor weather.

ADDITIVE ONLY: this file does not modify telemetry.py or appliances.py.
If this route fails for ANY reason, it returns a normal 200 response with
model_available=False (see the try/except at the bottom) rather than a
500 -- callers (the Streamlit frontend, or anything else) should never
need special-case error handling to stay working when ML is unavailable.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.ml_bridge import predict_energy
from app.weather_client import DEFAULT_LAT, DEFAULT_LON, get_outside_conditions

router = APIRouter(prefix="/api/predict", tags=["prediction"])

SCOPE_NOTE = (
    "This is a WHOLE-HOUSEHOLD appliance-energy estimate (Wh, ~10-minute-"
    "interval scale), not a prediction specific to this one appliance. "
    "The model was trained on the UCI Appliances Energy Prediction dataset "
    "(a single Belgian home) and is not validated for Indian households or "
    "Indian climate conditions. Treat it as an indicative trend signal, not "
    "ground truth."
)


@router.get("/{appliance_id}", response_model=schemas.PredictionOut)
def predict_household_energy(
    appliance_id: str,
    lat: float = Query(default=DEFAULT_LAT, description="Latitude for outdoor weather lookup"),
    lon: float = Query(default=DEFAULT_LON, description="Longitude for outdoor weather lookup"),
    db: Session = Depends(get_db),
):
    """
    Predict near-term whole-household appliance energy (Wh) using this
    appliance's latest stored telemetry (indoor temperature/humidity +
    most recent power reading) plus live outdoor weather.

    Returns 404 only if the appliance_id itself is unknown (matches the
    existing /api/appliances and /api/telemetry behaviour). Any OTHER
    failure -- no telemetry yet, model not trained, weather API down --
    is reported as a normal 200 response with model_available=False, so
    the frontend can render a graceful fallback instead of handling an
    HTTP error.
    """
    appliance = db.query(models.Appliance).filter(models.Appliance.id == appliance_id).first()
    if appliance is None:
        raise HTTPException(status_code=404, detail=f"Appliance '{appliance_id}' not found")

    latest = (
        db.query(models.Telemetry)
        .filter(models.Telemetry.appliance_id == appliance_id)
        .order_by(models.Telemetry.timestamp.desc())
        .first()
    )

    if latest is None or latest.temperature is None or latest.humidity is None or latest.power_watts is None:
        return schemas.PredictionOut(
            appliance_id=appliance_id,
            model_available=False,
            scope_note=SCOPE_NOTE,
            error="Not enough telemetry yet for this appliance (need temperature, humidity, and power_watts "
                  "on at least one stored reading).",
        )

    outdoor_temp, outdoor_humidity, outdoor_source = get_outside_conditions(lat=lat, lon=lon)

    # UNIT NOTE: our simulator reports instantaneous power_watts, while the
    # model's target/lag feature is Wh consumed over a 10-minute interval.
    # We approximate: Wh_over_10min ~= watts * (10 minutes / 60 minutes).
    # This is a simplifying assumption (assumes roughly steady power over
    # the interval), documented here rather than silently applied.
    recent_energy_wh = latest.power_watts * (10.0 / 60.0)

    payload = {
        "indoor_temperature": latest.temperature,
        "indoor_humidity": latest.humidity,
        "outdoor_temperature": outdoor_temp,
        "outdoor_humidity": outdoor_humidity,
        "recent_energy_wh": recent_energy_wh,
        "timestamp": latest.timestamp.isoformat(),
    }

    try:
        result = predict_energy(payload)
    except Exception as exc:  # noqa: BLE001 - final safety net; predict_energy
        # already catches internally, but this route must never 500 either.
        result = {
            "model_available": False,
            "predicted_energy_wh": None,
            "confidence_rmse": None,
            "model_version": None,
            "error": f"Unexpected error calling ML module: {type(exc).__name__}: {exc}",
        }

    return schemas.PredictionOut(
        appliance_id=appliance_id,
        model_available=result["model_available"],
        predicted_household_energy_wh=result.get("predicted_energy_wh"),
        confidence_rmse=result.get("confidence_rmse"),
        model_version=result.get("model_version"),
        scope_note=SCOPE_NOTE,
        inputs_used=schemas.PredictionInputsUsed(
            indoor_temperature=latest.temperature,
            indoor_humidity=latest.humidity,
            outdoor_temperature=outdoor_temp,
            outdoor_humidity=outdoor_humidity,
            outdoor_source=outdoor_source,
            recent_energy_wh=round(recent_energy_wh, 2),
            telemetry_timestamp=latest.timestamp,
        ),
        error=result.get("error"),
    )
