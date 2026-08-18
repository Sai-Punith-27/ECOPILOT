"""
Pydantic schemas — these define what goes IN and OUT of the API,
separate from the database models. This keeps validation rules
in one clear place.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ApplianceOut(BaseModel):
    """What we return when the client asks about an appliance."""

    id: str
    type: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class TelemetryCreate(BaseModel):
    """What a client (simulator, ESP32, or test tool) sends us."""

    appliance_id: str = Field(..., min_length=1, description="e.g. 'ac_01'")

    temperature: Optional[float] = Field(default=None, ge=-30, le=100, description="Degrees Celsius")
    humidity: Optional[float] = Field(default=None, ge=0, le=100, description="Relative humidity percent")
    power_watts: Optional[float] = Field(default=None, ge=0, description="Power draw in watts")
    water_liters: Optional[float] = Field(default=None, ge=0, description="Water used, in liters")

    occupancy: Optional[bool] = Field(default=None, description="Room occupied (AC)")
    door_open: Optional[bool] = Field(default=None, description="Fridge door open")

    water_level: Optional[float] = Field(default=None, ge=0, le=100, description="Tank level percent (cooler)")
    load_kg: Optional[float] = Field(default=None, ge=0, le=50, description="Laundry load weight in kg")
    fan_speed: Optional[int] = Field(default=None, ge=0, le=5, description="Fan speed level")
    pump_duty: Optional[float] = Field(default=None, ge=0, le=100, description="Water pump duty cycle percent")
    setpoint: Optional[float] = Field(default=None, ge=-30, le=100, description="Target temperature/setting")
    cycle: Optional[str] = Field(default=None, max_length=30, description="e.g. 'wash', 'cooling', 'idle'")

    timestamp: Optional[datetime] = Field(default=None, description="Reading time; server time used if omitted")


class TelemetryOut(TelemetryCreate):
    """What we return after storing (or when listing) telemetry."""

    id: int
    timestamp: datetime  # always present in the response, unlike in the input

    model_config = ConfigDict(from_attributes=True)


class PredictionInputsUsed(BaseModel):
    """Echoes back exactly what went into the prediction, for transparency."""

    indoor_temperature: Optional[float] = None
    indoor_humidity: Optional[float] = None
    outdoor_temperature: Optional[float] = None
    outdoor_humidity: Optional[float] = None
    outdoor_source: Optional[str] = None  # "live (Open-Meteo)" or fallback note
    recent_energy_wh: Optional[float] = None
    telemetry_timestamp: Optional[datetime] = None


class PredictionOut(BaseModel):
    """
    Response for GET /api/predict/{appliance_id}.

    IMPORTANT SCOPE NOTE (see also ai-optimizers/ml/model.py docstring):
    predicted_household_energy_wh is a WHOLE-HOUSEHOLD energy estimate
    (the model was trained on the UCI Appliances Energy Prediction
    dataset, a single Belgian home, whose only target is total household
    appliance energy -- it has no per-appliance breakdown). It is NOT a
    prediction of this one appliance's own future energy draw. The field
    name and `scope_note` both say this explicitly so it can't be
    misread as per-appliance accuracy.
    """

    appliance_id: str
    model_available: bool
    predicted_household_energy_wh: Optional[float] = None
    confidence_rmse: Optional[float] = None
    model_version: Optional[str] = None
    scope_note: str
    inputs_used: Optional[PredictionInputsUsed] = None
    error: Optional[str] = None
