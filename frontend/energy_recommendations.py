"""
Deterministic smart energy-saving recommendations for the live dashboard.

This module deliberately contains no Streamlit, network, or model-loading code.
It turns the current telemetry plus the existing optimizer/diagnostic outputs into
an honest, user-facing summary. Numeric impacts are copied from the existing
household optimizer and retain that optimizer's appliance-specific timeframe.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple


APPLIANCE_ORDER = ("ac", "refrigerator", "washing_machine", "cooler")
APPLIANCE_NAMES = {
    "ac": "Air Conditioner",
    "refrigerator": "Refrigerator",
    "washing_machine": "Washing Machine",
    "cooler": "Desert Cooler",
}

# These thresholds are deliberately conservative and easy to explain during a demo.
AC_EFFICIENT_SETPOINT_C = 24.0
AC_HIGH_POWER_W = 1500.0
FRIDGE_SAFE_MIN_C = 1.0
FRIDGE_SAFE_MAX_C = 4.0
WASHER_SMALL_LOAD_KG = 2.0
COOLER_LOW_WATER_PERCENT = 15.0
COOLER_HIGH_HUMIDITY_PERCENT = 70.0



def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Return a finite-looking numeric value without raising on bad telemetry."""
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default



def _reading(raw_readings: Dict[str, Dict[str, Any]], appliance: str) -> Dict[str, Any]:
    value = raw_readings.get(appliance, {})
    return value if isinstance(value, dict) else {}



def _optimizer_recommendation(
    recommendations_by_appliance: Dict[str, Dict[str, Any]], appliance: str
) -> Dict[str, Any]:
    value = recommendations_by_appliance.get(appliance, {})
    return value if isinstance(value, dict) else {}



def _impact_from_optimizer(
    optimizer_rec: Dict[str, Any], timeframe: str
) -> Tuple[str, Optional[float]]:
    """Copy an existing optimizer saving, never inventing a new measurement."""
    baseline = _number(optimizer_rec.get("baseline_energy_kwh"))
    optimized = _number(optimizer_rec.get("optimized_energy_kwh"))
    if baseline is None or optimized is None:
        return "Qualitative only — the current telemetry does not support a reliable kWh estimate.", None

    saving = round(max(baseline - optimized, 0.0), 4)
    if saving <= 0.0:
        return "No material numeric saving was identified by the existing deterministic optimizer.", None

    return (
        f"Approximately {saving:.3f} kWh/{timeframe} according to the existing "
        "deterministic optimizer (an estimate, not a measured bill reduction).",
        saving,
    )



def _qualitative_impact(text: str) -> Tuple[str, Optional[float]]:
    return text, None



def _base_record(
    appliance: str,
    observation: str,
    action: str,
    priority: str,
    impact: Tuple[str, Optional[float]],
) -> Dict[str, Any]:
    impact_text, saving = impact
    return {
        "appliance": appliance,
        "appliance_name": APPLIANCE_NAMES[appliance],
        "observation": observation,
        "action": action,
        "priority": priority,
        "impact": impact_text,
        "estimated_energy_saving_kwh": saving,
    }



def _build_ac(
    reading: Dict[str, Any], optimizer_rec: Dict[str, Any]
) -> Dict[str, Any]:
    temperature = _number(reading.get("temperature"), 28.0)
    setpoint = _number(reading.get("setpoint"), 24.0)
    power = _number(reading.get("power_watts"), 0.0)
    occupied = reading.get("occupancy")
    optimizer_action = optimizer_rec.get("recommendation", "Use the energy-efficient AC setting.")

    if occupied is False and power > 100.0:
        observation = f"The room is unoccupied while the AC reports approximately {power:.0f} W."
        action = "Turn the AC off or use fan/eco mode until the room is occupied."
        impact = _qualitative_impact(
            "Potentially high — reducing unnecessary runtime should save energy, but an off-state baseline is not measured here."
        )
        priority = "High" if power >= AC_HIGH_POWER_W else "Medium"
    elif setpoint < AC_EFFICIENT_SETPOINT_C:
        observation = (
            f"The AC setpoint is {setpoint:.1f}°C while the room is {temperature:.1f}°C; "
            "colder settings generally increase compressor work."
        )
        action = "Raise the setpoint gradually toward 24–26°C while keeping the room comfortable."
        impact = _impact_from_optimizer(optimizer_rec, "hour-equivalent")
        priority = "High" if power >= AC_HIGH_POWER_W else "Medium"
    elif power >= AC_HIGH_POWER_W:
        observation = f"The AC is drawing a high instantaneous load of approximately {power:.0f} W."
        action = str(optimizer_action)
        impact = _impact_from_optimizer(optimizer_rec, "hour-equivalent")
        priority = "Medium"
    else:
        observation = "The AC telemetry is within the current comfort-aware operating range."
        action = str(optimizer_action)
        impact = _impact_from_optimizer(optimizer_rec, "hour-equivalent")
        priority = "Low"

    return _base_record("ac", observation, action, priority, impact)



def _build_refrigerator(
    reading: Dict[str, Any],
    optimizer_rec: Dict[str, Any],
    fridge_anomaly: Dict[str, Any],
) -> Dict[str, Any]:
    temperature = _number(reading.get("temperature"), 4.0)
    power = _number(reading.get("power_watts"), 0.0)
    anomaly_status = fridge_anomaly.get("status")
    anomaly_score = _number(fridge_anomaly.get("anomaly_score"), 0.0) or 0.0
    anomaly_action = fridge_anomaly.get("recommendation")
    optimizer_action = optimizer_rec.get("recommendation", "Keep the refrigerator in its safe efficient range.")

    if anomaly_status == "WARNING":
        observation = (
            f"Refrigerator power is unusual for the current session (approximately {power:.0f} W; "
            f"advisory score {anomaly_score:.0f}/100)."
        )
        action = str(anomaly_action or optimizer_action)
        impact = _qualitative_impact(
            "Potentially avoidable — a single live reading is not enough to claim a reliable kWh saving."
        )
        priority = "High" if anomaly_score >= 70.0 else "Medium"
    elif temperature < FRIDGE_SAFE_MIN_C or temperature > FRIDGE_SAFE_MAX_C:
        observation = f"The internal temperature is {temperature:.1f}°C, outside the illustrative 1–4°C safe range."
        action = "Check the temperature setting, door seal, and ventilation; continue monitoring before changing settings."
        impact = _qualitative_impact(
            "Safety first — no energy saving is claimed until the refrigerator is holding a safe temperature."
        )
        priority = "Medium"
    else:
        observation = f"Internal temperature is {temperature:.1f}°C and power is not flagged as unusual."
        action = str(optimizer_action)
        impact = _impact_from_optimizer(optimizer_rec, "day")
        priority = "Low" if impact[1] is None else "Medium"

    return _base_record("refrigerator", observation, action, priority, impact)



def _build_washing_machine(
    reading: Dict[str, Any], optimizer_rec: Dict[str, Any]
) -> Dict[str, Any]:
    cycle = str(reading.get("cycle") or "IDLE").upper()
    load = _number(reading.get("load_kg"), 0.0) or 0.0
    optimizer_action = str(optimizer_rec.get("recommendation", "Use an efficient wash mode."))

    if cycle == "IDLE":
        observation = "The washing machine is idle; there is no active-cycle energy baseline to measure."
        action = f"Wait for a fuller load, then {optimizer_action[0].lower() + optimizer_action[1:]}."
        impact = _qualitative_impact(
            "Qualitative only — a complete active wash cycle is needed before estimating cycle savings from telemetry."
        )
        priority = "Low"
    elif load < WASHER_SMALL_LOAD_KG:
        observation = f"An active cycle reports a small {load:.1f} kg load."
        action = f"When practical, combine loads and {optimizer_action[0].lower() + optimizer_action[1:]}."
        impact = _impact_from_optimizer(optimizer_rec, "wash-cycle")
        priority = "Medium"
    else:
        observation = f"The washer is in {cycle.lower()} with a {load:.1f} kg load."
        action = optimizer_action
        impact = _impact_from_optimizer(optimizer_rec, "wash-cycle")
        priority = "Low" if impact[1] is None else "Medium"

    return _base_record("washing_machine", observation, action, priority, impact)



def _build_cooler(
    reading: Dict[str, Any],
    optimizer_rec: Dict[str, Any],
    dryrun_info: Tuple[Any, Any, Any],
) -> Dict[str, Any]:
    temperature = _number(reading.get("temperature"), 30.0)
    humidity = _number(reading.get("humidity"), 40.0)
    water_level = _number(reading.get("water_level"), 80.0)
    pump_duty = _number(reading.get("pump_duty"), 0.0)
    optimizer_action = str(optimizer_rec.get("recommendation", "Use the efficient cooler setting."))
    dryrun_flag = bool(dryrun_info[0]) if isinstance(dryrun_info, (tuple, list)) and dryrun_info else False

    if dryrun_flag:
        observation = "The pump is running while recent water consumption is near zero, matching a dry-run pattern."
        action = "Check the tank and water feed; keep the pump from running dry before optimizing comfort."
        impact = _qualitative_impact(
            "Potentially high — protecting the pump and avoiding unproductive runtime matters, but no kWh saving is claimed."
        )
        priority = "High"
    elif water_level <= COOLER_LOW_WATER_PERCENT:
        observation = f"The cooler water level is low at {water_level:.1f}%."
        action = "Refill the tank before using the pump; keep the pump off below the safe water threshold."
        impact = _qualitative_impact(
            "Safety first — refill and restore effective cooling before estimating an energy saving."
        )
        priority = "High"
    elif humidity >= COOLER_HIGH_HUMIDITY_PERCENT and pump_duty > 0.0:
        observation = (
            f"Humidity is high at {humidity:.1f}% while the pump is at {pump_duty:.1f}%; "
            "evaporative cooling is less effective in humid air."
        )
        action = "Reduce pump duty and rely more on fan-only circulation when comfort allows."
        impact = _qualitative_impact(
            "Potentially useful — reducing pump use can save water and energy, but the saving depends on comfort and airflow."
        )
        priority = "Medium"
    elif reading.get("occupancy") is False and (_number(reading.get("power_watts"), 0.0) or 0.0) > 50.0:
        observation = f"The room is unoccupied while the cooler is drawing approximately {_number(reading.get('power_watts'), 0.0):.0f} W."
        action = "Lower the fan/pump setting or turn the cooler off until the room is occupied."
        impact = _qualitative_impact(
            "Potentially high — unnecessary runtime can be avoided, but an off-state baseline is not measured here."
        )
        priority = "Medium"
    else:
        observation = f"The cooler is operating at {temperature:.1f}°C and {humidity:.1f}% RH without a safety alert."
        action = optimizer_action
        impact = _impact_from_optimizer(optimizer_rec, "hour-equivalent")
        priority = "Low" if impact[1] is None else "Medium"

    return _base_record("cooler", observation, action, priority, impact)



def _available_ml_context(ml_predictions: Optional[Dict[str, Dict[str, Any]]]) -> Optional[str]:
    if not isinstance(ml_predictions, dict):
        return None
    available = [
        name
        for appliance_id, name in (("ac_01", "AC"), ("cooler_01", "Desert Cooler"))
        if isinstance(ml_predictions.get(appliance_id), dict)
        and ml_predictions[appliance_id].get("model_available")
    ]
    if not available:
        return None
    return (
        "ML context is available for "
        + " and ".join(available)
        + "; those forecasts are whole-household estimates and are not treated as appliance-specific savings."
    )



def build_energy_recommendations(
    raw_readings: Dict[str, Dict[str, Any]],
    household_report: Dict[str, Any],
    fridge_anomaly: Dict[str, Any],
    dryrun_info: Tuple[Any, Any, Any],
    ml_predictions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build four deterministic, display-ready recommendations from live state."""
    raw_readings = raw_readings if isinstance(raw_readings, dict) else {}
    household_report = household_report if isinstance(household_report, dict) else {}
    fridge_anomaly = fridge_anomaly if isinstance(fridge_anomaly, dict) else {}

    optimizer_recs = {
        rec.get("appliance"): rec
        for rec in household_report.get("recommendations", [])
        if isinstance(rec, dict) and rec.get("appliance")
    }

    recommendations = [
        _build_ac(_reading(raw_readings, "ac"), _optimizer_recommendation(optimizer_recs, "ac")),
        _build_refrigerator(
            _reading(raw_readings, "fridge"),
            _optimizer_recommendation(optimizer_recs, "refrigerator"),
            fridge_anomaly,
        ),
        _build_washing_machine(
            _reading(raw_readings, "washer"),
            _optimizer_recommendation(optimizer_recs, "washing_machine"),
        ),
        _build_cooler(
            _reading(raw_readings, "cooler"),
            _optimizer_recommendation(optimizer_recs, "cooler"),
            dryrun_info,
        ),
    ]

    priority_counts = {priority: sum(r["priority"] == priority for r in recommendations) for priority in ("High", "Medium", "Low")}
    numeric_savings = [
        r["estimated_energy_saving_kwh"]
        for r in recommendations
        if r["estimated_energy_saving_kwh"] is not None
    ]
    summary = {
        "total_recommendations": len(recommendations),
        "opportunity_count": priority_counts["High"] + priority_counts["Medium"],
        "high_priority_count": priority_counts["High"],
        "medium_priority_count": priority_counts["Medium"],
        "low_priority_count": priority_counts["Low"],
        "estimated_energy_saving_kwh": round(sum(numeric_savings), 4) if numeric_savings else None,
        "estimated_saving_note": (
            "Combined modeled savings across appliance-specific timeframes; do not add these figures as a single daily bill forecast."
            if numeric_savings
            else "No reliable numeric saving is available from the current readings."
        ),
        "ml_context": _available_ml_context(ml_predictions),
    }
    return {"recommendations": recommendations, "summary": summary}
