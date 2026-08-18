"""
household_optimizer.py
------------------------
Household-level EcoPilot aggregator.
 
Takes the CURRENT STATE of all four appliances (AC, refrigerator, washing
machine, desert cooler), runs each appliance's own optimization module,
and combines the results into a single household-level report: total
baseline/optimized energy, water, cost, carbon, an overall resource
efficiency score, and a list of per-appliance recommendations.
 
Reuses the appliance modules already built in this package rather than
re-implementing their logic:
  - ac_optimizer.py       (AC setpoint recommendation)
  - wm_optimizer.py       (washing machine mode recommendation)
  - cooler_optimizer.py   (desert cooler fan/pump recommendation)
  - calculations.py       (shared cost/carbon constants and formulas)
 
There is no standalone "fridge recommendation" module in this package
(fridge_anomaly_detector.py is diagnostic/advisory only, not a settings
optimizer), so this file includes a small, self-contained refrigerator
recommendation (`_recommend_refrigerator`) built on the same
`calculations.fridge_energy_kwh` formula used elsewhere in the project.
 
IMPORTANT — units and timeframes (read this before interpreting totals)
=========================================================================
The four appliance modules were each built independently and naturally
report figures over different characteristic timeframes:
 
  - AC / Cooler:      a 1-hour-equivalent power snapshot (their `power`
                       input, in Watts, converted directly to kWh).
  - Washing machine:  a full wash-cycle total (kWh / liters for the whole
                       cycle).
  - Refrigerator:     a full-day (24h) total, matching
                       calculations.fridge_energy_kwh's default.
 
This module SUMS these as-is into single "total" figures for a combined
household advisory snapshot. That is a deliberate simplification for
this MVP: treat the totals as an illustrative COMBINED resource picture
across appliances with different duty cycles, not a strictly
time-normalized physical measurement. All numbers are otherwise
deterministic, computed only from the state you provide, and consistent
with the disclaimers in the other EcoPilot AI modules: SIMULATED
estimates for demo purposes, not real-world measured savings.
"""
 
from typing import Dict, List, Optional
 
from calculations import (
    ELECTRICITY_TARIFF_INR_PER_KWH,
    WATER_COST_INR_PER_LITER,
    GRID_EMISSION_FACTOR_KG_CO2_PER_KWH,
    compute_cost_inr,
    compute_carbon_kg,
    fridge_energy_kwh,
    clamp,
)
from ac_optimizer import optimize_ac
from wm_optimizer import optimize_washing_machine
from cooler_optimizer import optimize_cooler
 
# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
 
# Same relative importances used by the deeper multi-objective optimizer in
# optimizer.py, reused here so the household resource_score weighs the same
# priorities: energy first, then water, then cost and carbon equally.
RESOURCE_SCORE_WEIGHTS: Dict[str, float] = {
    "energy": 0.35,
    "water": 0.25,
    "cost": 0.20,
    "carbon": 0.20,
}
 
# Refrigerator safe food-storage band (matches the rest of the EcoPilot codebase).
FRIDGE_SAFE_MIN_C: float = 1.0
FRIDGE_SAFE_MAX_C: float = 4.0
FRIDGE_DEFAULT_RATED_POWER_W: float = 150.0
FRIDGE_SECONDS_OPEN_PER_DOOR_EVENT: float = 30.0  # assumption: ~30s average per door opening
 
 
# ---------------------------------------------------------------------------
# Refrigerator recommendation (self-contained; no standalone module exists)
# ---------------------------------------------------------------------------
 
def _recommend_refrigerator(state: Dict) -> Dict:
    """
    Minimal, transparent refrigerator recommendation for household-level
    use: check whether the current target temperature is colder than
    necessary, and if so, propose raising it by 1C -- never outside the
    safe 1-4C food-storage band. Uses calculations.fridge_energy_kwh (a
    24h/daily estimate) for both the baseline and candidate.
    """
    internal_temperature = state["internal_temperature"]
    target_temperature = state["target_temperature"]
    ambient_temperature = state["ambient_temperature"]
    door_open_count = state.get("door_open_count", 0)
    rated_power_w = state.get("rated_power_w", FRIDGE_DEFAULT_RATED_POWER_W)
    frost_thickness_mm = state.get("frost_thickness_mm", 0.0)
 
    door_open_seconds = door_open_count * FRIDGE_SECONDS_OPEN_PER_DOOR_EVENT
 
    baseline_target = clamp(target_temperature, FRIDGE_SAFE_MIN_C, FRIDGE_SAFE_MAX_C)
    baseline_energy = fridge_energy_kwh(
        baseline_target, ambient_temperature, door_open_seconds, frost_thickness_mm, rated_power_w
    )
 
    candidates = [baseline_target]
    if baseline_target < FRIDGE_SAFE_MAX_C:
        candidates.append(min(baseline_target + 1.0, FRIDGE_SAFE_MAX_C))
 
    best_target = baseline_target
    best_energy = baseline_energy
    for t in candidates:
        e = fridge_energy_kwh(t, ambient_temperature, door_open_seconds, frost_thickness_mm, rated_power_w)
        if e < best_energy:
            best_energy = e
            best_target = t
 
    if best_target > baseline_target:
        reason = (
            f"Current setpoint ({baseline_target:.1f}C) is colder than necessary; raising it to "
            f"{best_target:.1f}C still stays within the safe {FRIDGE_SAFE_MIN_C:.0f}-{FRIDGE_SAFE_MAX_C:.0f}C "
            f"food-storage range while reducing compressor duty cycle."
        )
    else:
        reason = "Current setpoint is already efficient within the safe food-storage range; no change recommended."
 
    return {
        "appliance": "refrigerator",
        "recommendation": (
            f"Keep setpoint at {best_target:.1f}C" if best_target == baseline_target
            else f"Raise setpoint to {best_target:.1f}C"
        ),
        "baseline_energy_kwh": baseline_energy,
        "optimized_energy_kwh": best_energy,
        "baseline_water_liters": 0.0,
        "optimized_water_liters": 0.0,
        "reason": reason,
    }
 
 
# ---------------------------------------------------------------------------
# Per-appliance adapters -- normalize each module's output into a common shape
# ---------------------------------------------------------------------------
 
def _run_ac(state: Dict) -> Dict:
    result = optimize_ac(
        temperature=state["temperature"],
        humidity=state["humidity"],
        occupancy=state["occupancy"],
        current_setpoint=state["current_setpoint"],
        current_power=state["current_power"],
        outside_temperature=state["outside_temperature"],
        min_comfort_threshold=state.get("min_comfort_threshold", 70.0),
    )
    baseline_energy_kwh = round(result["baseline_energy"] / 1000.0, 4)
    optimized_energy_kwh = round(result["optimized_energy"] / 1000.0, 4)
    return {
        "appliance": "ac",
        "recommendation": f"Set AC to {result['recommended_setpoint']}C",
        "baseline_energy_kwh": baseline_energy_kwh,
        "optimized_energy_kwh": optimized_energy_kwh,
        "baseline_water_liters": 0.0,
        "optimized_water_liters": 0.0,
        "reason": result["reason"],
    }
 
 
def _run_washing_machine(state: Dict) -> Dict:
    electricity_cost = state.get("electricity_cost", ELECTRICITY_TARIFF_INR_PER_KWH)
    water_cost_per_liter = state.get("water_cost_per_liter", WATER_COST_INR_PER_LITER)
 
    result = optimize_washing_machine(
        load_kg=state["load_kg"],
        dirt_level=state["dirt_level"],
        water_hardness=state["water_hardness"],
        current_cycle=state["current_cycle"],
        current_water=state["current_water"],
        current_energy=state["current_energy"],
        deadline_minutes=state["deadline_minutes"],
        electricity_cost=electricity_cost,
        water_cost_per_liter=water_cost_per_liter,
        min_performance_threshold=state.get("min_performance_threshold", 70.0),
    )
    baseline_energy = result["details"]["baseline_energy"]
    baseline_water = result["details"]["baseline_water"]
    optimized_energy = round(baseline_energy - result["energy_saving"], 4)
    optimized_water = round(baseline_water - result["water_saving"], 4)
    return {
        "appliance": "washing_machine",
        "recommendation": f"Use {result['recommended_mode']} mode",
        "baseline_energy_kwh": baseline_energy,
        "optimized_energy_kwh": optimized_energy,
        "baseline_water_liters": baseline_water,
        "optimized_water_liters": optimized_water,
        "reason": result["reason"],
    }
 
 
def _run_cooler(state: Dict) -> Dict:
    result = optimize_cooler(
        temperature=state["temperature"],
        humidity=state["humidity"],
        occupancy=state["occupancy"],
        water_level=state["water_level"],
        fan_speed=state["fan_speed"],
        pump_duty=state["pump_duty"],
        power=state["power"],
        min_comfort_threshold=state.get("min_comfort_threshold", 70.0),
        min_water_level_percent=state.get("min_water_level_percent", 15.0),
    )
    baseline_energy_kwh = round(result["details"]["baseline_energy"] / 1000.0, 4)
    optimized_energy_kwh = round(baseline_energy_kwh - result["estimated_energy_saving"] / 1000.0, 4)
    baseline_water_liters = result["details"]["baseline_water_lph"]  # 1-hour window -> liters == L/h
    optimized_water_liters = round(baseline_water_liters - result["estimated_water_saving"], 4)
    return {
        "appliance": "cooler",
        "recommendation": (
            f"Set fan speed {result['recommended_fan_speed']}, "
            f"pump duty {result['recommended_pump_duty']}%"
        ),
        "baseline_energy_kwh": baseline_energy_kwh,
        "optimized_energy_kwh": optimized_energy_kwh,
        "baseline_water_liters": baseline_water_liters,
        "optimized_water_liters": optimized_water_liters,
        "reason": result["reason"],
    }
 
 
# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
 
def optimize_household(
    ac: Dict,
    refrigerator: Dict,
    washing_machine: Dict,
    cooler: Dict,
) -> Dict:
    """
    Run all four appliance optimizers against the given current-state
    dicts and return a combined household report.
 
    Each argument is a flat dict of the fields that appliance's own
    optimizer requires (see the README / test dataset for exact field
    names). All computation is deterministic and based only on the
    provided state -- no external calls, no randomness.
 
    Returns:
        {
          "energy": {"baseline_kwh": ..., "optimized_kwh": ..., "saving_kwh": ...},
          "water":  {"baseline_liters": ..., "optimized_liters": ..., "saving_liters": ...},
          "cost":   {"baseline_inr": ..., "optimized_inr": ..., "saving_inr": ...},
          "carbon": {"baseline_kg": ..., "optimized_kg": ..., "saving_kg": ...},
          "resource_score": ...,   # 0-100, higher = current setup already closer to optimal
          "recommendations": [ {appliance, recommendation, ...}, ... ],
        }
    """
    per_appliance: List[Dict] = [
        _run_ac(ac),
        _recommend_refrigerator(refrigerator),
        _run_washing_machine(washing_machine),
        _run_cooler(cooler),
    ]
 
    baseline_energy = sum(a["baseline_energy_kwh"] for a in per_appliance)
    optimized_energy = sum(a["optimized_energy_kwh"] for a in per_appliance)
    baseline_water = sum(a["baseline_water_liters"] for a in per_appliance)
    optimized_water = sum(a["optimized_water_liters"] for a in per_appliance)
 
    baseline_cost = compute_cost_inr(baseline_energy, baseline_water)
    optimized_cost = compute_cost_inr(optimized_energy, optimized_water)
 
    baseline_carbon = compute_carbon_kg(baseline_energy)
    optimized_carbon = compute_carbon_kg(optimized_energy)
 
    resource_score = _compute_resource_score(
        baseline_energy, optimized_energy,
        baseline_water, optimized_water,
        baseline_cost, optimized_cost,
        baseline_carbon, optimized_carbon,
    )
 
    recommendations = [
        {
            "appliance": a["appliance"],
            "recommendation": a["recommendation"],
            "baseline_energy_kwh": a["baseline_energy_kwh"],
            "optimized_energy_kwh": a["optimized_energy_kwh"],
            "baseline_water_liters": a["baseline_water_liters"],
            "optimized_water_liters": a["optimized_water_liters"],
            "reason": a["reason"],
        }
        for a in per_appliance
    ]
 
    return {
        "energy": {
            "baseline_kwh": round(baseline_energy, 4),
            "optimized_kwh": round(optimized_energy, 4),
            "saving_kwh": round(baseline_energy - optimized_energy, 4),
        },
        "water": {
            "baseline_liters": round(baseline_water, 4),
            "optimized_liters": round(optimized_water, 4),
            "saving_liters": round(baseline_water - optimized_water, 4),
        },
        "cost": {
            "baseline_inr": baseline_cost,
            "optimized_inr": optimized_cost,
            "saving_inr": round(baseline_cost - optimized_cost, 2),
        },
        "carbon": {
            "baseline_kg": baseline_carbon,
            "optimized_kg": optimized_carbon,
            "saving_kg": round(baseline_carbon - optimized_carbon, 3),
        },
        "resource_score": resource_score,
        "recommendations": recommendations,
    }
 
 
# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
 
def _safe_ratio(optimized: float, baseline: float) -> float:
    """optimized/baseline, clamped to [0, 1]. If baseline is 0 (nothing to
    save), treat as already perfectly efficient (ratio 1.0)."""
    if baseline <= 0:
        return 1.0
    return clamp(optimized / baseline, 0.0, 1.0)
 
 
def _compute_resource_score(baseline_energy, optimized_energy,
                             baseline_water, optimized_water,
                             baseline_cost, optimized_cost,
                             baseline_carbon, optimized_carbon) -> float:
    """
    0-100 score: how close the household's CURRENT (baseline) behavior
    already is to the optimized recommendation, weighted the same way as
    the multi-objective optimizer elsewhere in this project (energy
    weighted highest, then water, then cost/carbon equally). 100 = no
    identified waste at all; lower = more savings identified, i.e. more
    room for improvement.
    """
    w = RESOURCE_SCORE_WEIGHTS
    score = (
        w["energy"] * _safe_ratio(optimized_energy, baseline_energy)
        + w["water"] * _safe_ratio(optimized_water, baseline_water)
        + w["cost"] * _safe_ratio(optimized_cost, baseline_cost)
        + w["carbon"] * _safe_ratio(optimized_carbon, baseline_carbon)
    )
    return round(clamp(score * 100.0, 0.0, 100.0), 2)
 