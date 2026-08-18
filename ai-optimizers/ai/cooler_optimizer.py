"""
cooler_optimizer.py
--------------------
Standalone desert (evaporative) air-cooler optimization module for EcoPilot.
 
Given live sensor/state inputs (temperature, humidity, occupancy, tank
water level, current fan speed, current pump duty, current power draw),
this module evaluates a grid of (fan_speed, pump_duty) settings, estimates
energy, water use, and a humidity-aware cooling/comfort score for each,
and recommends the lowest-resource setting that still meets a minimum
comfort threshold.
 
Humidity-aware strategy
========================
Evaporative cooling works by evaporating water into the air -- which
barely works once the air is already humid. So as humidity rises, the
model:
  - reduces the cooling benefit credited to a given pump_duty
    (`_evaporative_effectiveness`), and
  - as a result, the optimizer naturally favors lower pump duty / more
    reliance on fan-only airflow at high humidity, cutting water use
    that wasn't buying any real cooling anyway.
 
Safety logic (hard constraint, not a scored trade-off)
=======================================================
If `water_level` is below the configured minimum, the pump is forced OFF
(pump_duty = 0) for every candidate considered -- this is enforced by
excluding any candidate with pump_duty > 0 from the candidate set
entirely, so it is never a matter of the optimizer merely "preferring"
fan-only; a wet pump running dry cannot be recommended under any
circumstance in this module.
 
Design goals (per spec):
- Transparent: every number comes from a simple, documented formula.
- Deterministic: same inputs always produce the same output.
- Self-contained: no dependency on the rest of the EcoPilot codebase.
 
DISCLAIMER: The energy/water/comfort formulas below are simplified
engineering approximations for a hackathon MVP demo. They are
directionally realistic but not lab-measured; treat all outputs as
SIMULATED estimates, not real-world measured savings.
"""
 
from typing import Dict, List, Sequence, Tuple
 
# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
 
FAN_SPEEDS: Sequence[int] = (1, 2, 3, 4, 5)
PUMP_DUTIES: Sequence[int] = (0, 25, 50, 75, 100)  # percent
 
DEFAULT_MIN_COMFORT_THRESHOLD: float = 70.0
DEFAULT_MIN_WATER_LEVEL_PERCENT: float = 15.0  # safety floor: pump forced OFF below this
 
# --- Energy model ---
# Fan power scales roughly linearly with fan speed (1-5); the pump adds a
# smaller extra draw proportional to its duty cycle.
FAN_POWER_WEIGHT: float = 1.0
PUMP_POWER_WEIGHT: float = 0.2  # pump at 100% duty adds ~20% of max fan power
 
# --- Water model ---
BASE_WATER_RATE_LPH: float = 0.9  # liters/hour at 100% pump duty, moderate humidity
HUMIDITY_WATER_BASELINE: float = 40.0
HUMIDITY_WATER_SENSITIVITY: float = 100.0  # divisor controlling how strongly humidity scales water use
 
# --- Comfort/cooling score model ---
COMFORT_AIRFLOW_MAX_POINTS: float = 40.0   # max points contributed by fan speed
COMFORT_EVAP_MAX_POINTS: float = 60.0      # max points contributed by evaporative cooling
EVAP_EFFECTIVENESS_HUMIDITY_BASELINE: float = 30.0
EVAP_EFFECTIVENESS_HUMIDITY_SENSITIVITY: float = 70.0
EVAP_EFFECTIVENESS_MIN: float = 0.10
EVAP_EFFECTIVENESS_MAX: float = 1.00
COMFORT_TEMP_TARGET_C: float = 30.0        # above this, extra cooling capacity is needed
COMFORT_TEMP_PENALTY_PER_DEGREE: float = 2.0
 
 
def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
 
 
# ---------------------------------------------------------------------------
# Per-setting estimators
# ---------------------------------------------------------------------------
 
def _load_factor(fan_speed: int, pump_duty: int) -> float:
    """Deterministic proxy for total electrical load at a given setting."""
    fan_factor = (fan_speed / max(FAN_SPEEDS)) * FAN_POWER_WEIGHT
    pump_factor = (pump_duty / 100.0) * PUMP_POWER_WEIGHT
    return fan_factor + pump_factor
 
 
def estimate_energy(fan_speed: int, pump_duty: int, current_fan_speed: int,
                     current_pump_duty: int, current_power: float) -> float:
    """
    Estimate power draw at (fan_speed, pump_duty), CALIBRATED against the
    real, sensor-reported `current_power` at the appliance's current
    settings. Self-consistent: estimate_energy(cur_fan, cur_pump, cur_fan,
    cur_pump, current_power) == current_power.
    """
    current_load = _load_factor(current_fan_speed, current_pump_duty)
    candidate_load = _load_factor(fan_speed, pump_duty)
    if current_load <= 0:
        return round(current_power, 3)
    return round(current_power * (candidate_load / current_load), 3)
 
 
def _evaporative_effectiveness(humidity: float) -> float:
    """How much cooling benefit a unit of pump duty actually buys, given
    ambient humidity. Falls off sharply as humidity rises -- this is the
    core of the humidity-aware strategy."""
    raw = 1.0 - (humidity - EVAP_EFFECTIVENESS_HUMIDITY_BASELINE) / EVAP_EFFECTIVENESS_HUMIDITY_SENSITIVITY
    return _clamp(raw, EVAP_EFFECTIVENESS_MIN, EVAP_EFFECTIVENESS_MAX)
 
 
def estimate_water_liters_per_hour(pump_duty: int, humidity: float) -> float:
    """
    Water evaporation rate (liters/hour). Scales with pump duty and with
    humidity (higher humidity => the pump still draws water even though
    it's buying less cooling benefit, which is exactly the waste this
    module targets).
    """
    humidity_multiplier = _clamp(
        1 + (humidity - HUMIDITY_WATER_BASELINE) / HUMIDITY_WATER_SENSITIVITY, 0.6, 1.4
    )
    rate = BASE_WATER_RATE_LPH * (pump_duty / 100.0) * humidity_multiplier
    return round(max(rate, 0.0), 3)
 
 
def estimate_comfort_score(fan_speed: int, pump_duty: int, temperature: float,
                            humidity: float, occupancy: bool) -> float:
    """
    Deterministic cooling/comfort score in [0, 100].
    - Unoccupied rooms always score 100: comfort isn't a binding concern,
      so the optimizer is free to pick the lowest-resource setting.
    - Occupied rooms get airflow credit (from fan speed) plus evaporative
      credit (from pump duty, discounted by humidity effectiveness), minus
      a penalty if the room is hotter than the comfort target.
    """
    if not occupancy:
        return 100.0
 
    airflow_component = (fan_speed / max(FAN_SPEEDS)) * COMFORT_AIRFLOW_MAX_POINTS
    evap_component = (pump_duty / 100.0) * _evaporative_effectiveness(humidity) * COMFORT_EVAP_MAX_POINTS
    temp_excess = max(temperature - COMFORT_TEMP_TARGET_C, 0.0)
    score = airflow_component + evap_component - temp_excess * COMFORT_TEMP_PENALTY_PER_DEGREE
    return round(_clamp(score, 0.0, 100.0), 2)
 
 
# ---------------------------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------------------------
 
def optimize_cooler(
    temperature: float,
    humidity: float,
    occupancy: bool,
    water_level: float,
    fan_speed: int,
    pump_duty: int,
    power: float,
    min_comfort_threshold: float = DEFAULT_MIN_COMFORT_THRESHOLD,
    min_water_level_percent: float = DEFAULT_MIN_WATER_LEVEL_PERCENT,
    fan_speeds: Sequence[int] = FAN_SPEEDS,
    pump_duties: Sequence[int] = PUMP_DUTIES,
) -> Dict:
    """
    Evaluate the (fan_speed, pump_duty) grid and recommend the
    lowest-resource setting that meets `min_comfort_threshold`.
 
    SAFETY: if `water_level` < `min_water_level_percent`, every candidate
    with pump_duty > 0 is excluded before scoring -- the pump is
    guaranteed OFF in the recommendation, not merely deprioritized.
 
    Returns:
        {
          "recommended_fan_speed": ...,
          "recommended_pump_duty": ...,
          "estimated_water_saving": ...,   # liters/hour saved vs. current setting
          "estimated_energy_saving": ...,  # power units saved vs. current setting
          "reason": ...,
          "details": {...}                 # full grid breakdown, for transparency
        }
    """
    pump_forced_off = water_level < min_water_level_percent
 
    baseline_pump_duty = 0 if pump_forced_off else pump_duty
    baseline_energy = estimate_energy(fan_speed, baseline_pump_duty, fan_speed, pump_duty, power)
    baseline_water = estimate_water_liters_per_hour(baseline_pump_duty, humidity)
 
    evaluations: List[Dict] = []
    for fs in fan_speeds:
        for pd in pump_duties:
            if pump_forced_off and pd > 0:
                continue  # SAFETY: pump must be OFF, never a candidate at all
            energy = estimate_energy(fs, pd, fan_speed, pump_duty, power)
            water = estimate_water_liters_per_hour(pd, humidity)
            comfort = estimate_comfort_score(fs, pd, temperature, humidity, occupancy)
            evaluations.append({
                "fan_speed": fs,
                "pump_duty": pd,
                "estimated_energy": energy,
                "estimated_water_lph": water,
                "comfort_score": comfort,
                "meets_comfort": comfort >= min_comfort_threshold,
            })
 
    chosen, reason = _select_setting(evaluations, min_comfort_threshold, pump_forced_off)
 
    water_saving = round(baseline_water - chosen["estimated_water_lph"], 3)
    energy_saving = round(baseline_energy - chosen["estimated_energy"], 3)
 
    if pump_forced_off:
        reason = (
            f"Water tank level ({water_level:.0f}%) is below the safe minimum of "
            f"{min_water_level_percent:.0f}%; pump is forced OFF to protect it from running dry. " + reason
        )
 
    return {
        "recommended_fan_speed": chosen["fan_speed"],
        "recommended_pump_duty": chosen["pump_duty"],
        "estimated_water_saving": water_saving,
        "estimated_energy_saving": energy_saving,
        "reason": reason,
        "details": {
            "baseline_fan_speed": fan_speed,
            "baseline_pump_duty": baseline_pump_duty,
            "baseline_energy": baseline_energy,
            "baseline_water_lph": baseline_water,
            "pump_forced_off": pump_forced_off,
            "chosen_comfort_score": chosen["comfort_score"],
            "evaluations": evaluations,
        },
    }
 
 
# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
 
def _select_setting(evaluations: List[Dict], min_comfort_threshold: float,
                     pump_forced_off: bool) -> Tuple[Dict, str]:
    """
    Selection logic (in order of preference):
      1. Among settings that meet the comfort threshold, pick the one with
         the lowest combined (normalized) energy + water.
      2. If none meet the threshold, fall back to the highest-comfort
         setting available and say so explicitly.
    """
    feasible = [e for e in evaluations if e["meets_comfort"]]
 
    if feasible:
        max_energy = max(e["estimated_energy"] for e in feasible) or 1.0
        max_water = max(e["estimated_water_lph"] for e in feasible) or 1.0
        for e in feasible:
            e["_resource_score"] = (e["estimated_energy"] / max_energy) + (e["estimated_water_lph"] / max_water)
        chosen = min(feasible, key=lambda e: (e["_resource_score"], e["pump_duty"], e["fan_speed"]))
        for e in feasible:
            e.pop("_resource_score", None)
 
        pump_note = (
            "pump stays OFF" if pump_forced_off else f"pump duty {chosen['pump_duty']}%"
        )
        reason = (
            f"Fan speed {chosen['fan_speed']} with {pump_note} gives the lowest combined energy and water use "
            f"among settings meeting the minimum comfort threshold of {min_comfort_threshold} "
            f"(comfort score {chosen['comfort_score']})."
        )
        return chosen, reason
 
    chosen = max(evaluations, key=lambda e: e["comfort_score"])
    reason = (
        f"No available setting reached the minimum comfort threshold of {min_comfort_threshold} "
        f"given current humidity/temperature; falling back to fan speed {chosen['fan_speed']} / "
        f"pump duty {chosen['pump_duty']}%, the best comfort achievable (score {chosen['comfort_score']})."
    )
    return chosen, reason