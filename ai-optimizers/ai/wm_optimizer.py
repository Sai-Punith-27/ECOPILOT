"""
wm_optimizer.py
----------------
Standalone washing-machine optimization module for EcoPilot.
 
Given the load's characteristics and a deadline, this module evaluates
three fixed modes (Normal, Eco, Quick), estimates water, energy, cycle
duration, and a cleaning/performance score for each, and recommends the
lowest-resource mode that both (a) meets a minimum cleaning/performance
threshold and (b) can finish by the given deadline.
 
Design goals (per spec):
- Transparent: every number comes from a simple, documented formula.
- Deterministic: same inputs always produce the same output.
- Self-contained: no dependency on the rest of the EcoPilot codebase.
 
DISCLAIMER: The water/energy/performance formulas below are simplified
engineering approximations for a hackathon MVP demo. They are
directionally realistic but not lab-measured; treat all outputs as
SIMULATED estimates, not real-world measured savings.
"""
 
from datetime import datetime, timedelta
from typing import Dict, List, Optional
 
# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
 
MODES = ("Normal", "Eco", "Quick")
 
DEFAULT_MIN_PERFORMANCE_THRESHOLD: float = 70.0
DEFAULT_WATER_COST_PER_LITER: float = 0.05  # illustrative, override if you have a real tariff
 
# Relative resource multipliers per mode vs. a "Normal" wash (calibrated
# against the real measured current_energy / current_water below).
MODE_ENERGY_MULTIPLIER: Dict[str, float] = {"Normal": 1.00, "Eco": 0.65, "Quick": 0.45}
MODE_WATER_MULTIPLIER: Dict[str, float] = {"Normal": 1.00, "Eco": 0.75, "Quick": 0.55}
 
# Baseline duration (minutes) at a reference 5kg load.
MODE_BASE_DURATION_MINUTES: Dict[str, float] = {"Normal": 60, "Eco": 90, "Quick": 30}
REFERENCE_LOAD_KG: float = 5.0
DURATION_MINUTES_PER_EXTRA_KG: float = 1.5
 
# Baseline cleaning/performance score (0-100) at medium dirt, normal hardness.
MODE_BASE_PERFORMANCE: Dict[str, float] = {"Normal": 90, "Eco": 85, "Quick": 60}
 
# How much each extra "dirt level step" (low->medium->high) hurts performance,
# per mode -- Quick suffers the most because there's less time/water to clean.
DIRT_LEVEL_STEPS: Dict[str, int] = {"low": 0, "medium": 1, "high": 2}
DIRT_PENALTY_PER_STEP: Dict[str, float] = {"Normal": 3, "Eco": 4, "Quick": 10}
 
# Water hardness (ppm) above this level needs extra rinsing; Eco/Quick suffer
# more because they use less water/time for rinsing.
HARDNESS_THRESHOLD_PPM: float = 150.0
HARDNESS_PENALTY_PER_50PPM: Dict[str, float] = {"Normal": 1, "Eco": 2, "Quick": 4}
 
# Large loads are harder to clean thoroughly on a short cycle.
OVERLOAD_THRESHOLD_KG: float = 6.0
OVERLOAD_PENALTY: Dict[str, float] = {"Normal": 0, "Eco": 2, "Quick": 8}
 
 
# ---------------------------------------------------------------------------
# Per-mode estimators
# ---------------------------------------------------------------------------
 
def estimate_duration_minutes(mode: str, load_kg: float) -> float:
    """Cycle duration grows with load size beyond the 5kg reference load,
    at the same per-kg rate for every mode (a bigger drum still needs more
    fill/drain/spin time regardless of mode)."""
    extra_kg = max(load_kg - REFERENCE_LOAD_KG, 0.0)
    return round(MODE_BASE_DURATION_MINUTES[mode] + extra_kg * DURATION_MINUTES_PER_EXTRA_KG, 1)
 
 
def estimate_energy(mode: str, current_cycle: str, current_energy: float) -> float:
    """
    Estimate energy for `mode`, CALIBRATED against the real, sensor-reported
    `current_energy` at `current_cycle`. This scales the measured baseline by
    the ratio of each mode's energy multiplier, so:
 
        estimate_energy(current_cycle, current_cycle, current_energy) == current_energy
    """
    ratio = MODE_ENERGY_MULTIPLIER[mode] / MODE_ENERGY_MULTIPLIER[current_cycle]
    return round(current_energy * ratio, 3)
 
 
def estimate_water(mode: str, current_cycle: str, current_water: float) -> float:
    """Same calibrated-ratio approach as estimate_energy, but for water (liters)."""
    ratio = MODE_WATER_MULTIPLIER[mode] / MODE_WATER_MULTIPLIER[current_cycle]
    return round(current_water * ratio, 2)
 
 
def estimate_performance(mode: str, dirt_level: str, load_kg: float, water_hardness: float) -> float:
    """
    Deterministic cleaning/performance score in [0, 100].
    Starts from the mode's baseline score and subtracts penalties for
    dirt level, water hardness, and overloading -- each penalty scaled
    per mode to reflect that faster/lighter modes cope worse with harder
    conditions.
    """
    dirt_key = dirt_level.lower()
    dirt_step = DIRT_LEVEL_STEPS.get(dirt_key, 1)  # default to 'medium' if unrecognized
    dirt_penalty = DIRT_PENALTY_PER_STEP[mode] * dirt_step
 
    hardness_steps = max(water_hardness - HARDNESS_THRESHOLD_PPM, 0.0) / 50.0
    hardness_penalty = HARDNESS_PENALTY_PER_50PPM[mode] * hardness_steps
 
    overload_penalty = OVERLOAD_PENALTY[mode] if load_kg > OVERLOAD_THRESHOLD_KG else 0.0
 
    score = MODE_BASE_PERFORMANCE[mode] - dirt_penalty - hardness_penalty - overload_penalty
    return round(max(0.0, min(100.0, score)), 2)
 
 
# ---------------------------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------------------------
 
def optimize_washing_machine(
    load_kg: float,
    dirt_level: str,
    water_hardness: float,
    current_cycle: str,
    current_water: float,
    current_energy: float,
    deadline_minutes: float,
    electricity_cost: float,
    water_cost_per_liter: float = DEFAULT_WATER_COST_PER_LITER,
    min_performance_threshold: float = DEFAULT_MIN_PERFORMANCE_THRESHOLD,
    now: Optional[datetime] = None,
) -> Dict:
    """
    Evaluate Normal / Eco / Quick and recommend the lowest-resource mode
    that meets both the minimum cleaning/performance threshold and the
    deadline (deadline_minutes = minutes from `now` by which the wash
    must be finished).
 
    `now` defaults to the real current time; pass an explicit datetime
    for deterministic/testable output.
 
    Returns:
        {
          "recommended_mode": ...,
          "recommended_start_time": ...,   # ISO 8601 string
          "water_saving": ...,             # liters saved vs. current_water
          "energy_saving": ...,            # kWh saved vs. current_energy
          "cost_saving": ...,              # currency saved vs. current baseline cost
          "reason": ...,
          "details": {...}                 # full per-mode breakdown, for transparency
        }
    """
    if now is None:
        now = datetime.now()
 
    current_cycle_norm = _normalize_mode(current_cycle)
    baseline_cost = current_energy * electricity_cost + current_water * water_cost_per_liter
 
    evaluations: List[Dict] = []
    for mode in MODES:
        duration = estimate_duration_minutes(mode, load_kg)
        energy = estimate_energy(mode, current_cycle_norm, current_energy)
        water = estimate_water(mode, current_cycle_norm, current_water)
        performance = estimate_performance(mode, dirt_level, load_kg, water_hardness)
        cost = energy * electricity_cost + water * water_cost_per_liter
 
        evaluations.append({
            "mode": mode,
            "water_consumption": water,
            "energy_consumption": energy,
            "cycle_duration_minutes": duration,
            "performance_score": performance,
            "cost": round(cost, 2),
            "meets_deadline": duration <= deadline_minutes,
            "meets_performance": performance >= min_performance_threshold,
        })
 
    chosen, reason = _select_mode(evaluations, deadline_minutes, min_performance_threshold)
 
    for e in evaluations:
        e.pop("_resource_score", None)
 
    deadline_time = now + timedelta(minutes=deadline_minutes)
    latest_start = deadline_time - timedelta(minutes=chosen["cycle_duration_minutes"])
    recommended_start_time = max(now, latest_start)
 
    water_saving = round(current_water - chosen["water_consumption"], 2)
    energy_saving = round(current_energy - chosen["energy_consumption"], 3)
    cost_saving = round(baseline_cost - chosen["cost"], 2)
 
    return {
        "recommended_mode": chosen["mode"],
        "recommended_start_time": recommended_start_time.isoformat(),
        "water_saving": water_saving,
        "energy_saving": energy_saving,
        "cost_saving": cost_saving,
        "reason": reason,
        "details": {
            "baseline_water": current_water,
            "baseline_energy": current_energy,
            "baseline_cost": round(baseline_cost, 2),
            "evaluations": evaluations,
        },
    }
 
 
# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
 
def _normalize_mode(mode: str) -> str:
    for m in MODES:
        if m.lower() == mode.strip().lower():
            return m
    # Unknown current_cycle: fall back to Normal as a safe calibration reference.
    return "Normal"
 
 
def _select_mode(evaluations: List[Dict], deadline_minutes: float,
                  min_performance_threshold: float) -> tuple[Dict, str]:
    """
    Selection logic (in order of preference):
      1. Among modes meeting BOTH the deadline and the performance threshold,
         pick the lowest combined resource usage (energy + water, each
         normalized against the most resource-hungry feasible candidate so
         the two units are comparable).
      2. If none meet both, but some meet the deadline, pick the
         highest-performance mode among those (best available given the
         time constraint) and say the performance threshold was relaxed.
      3. If none meet the deadline at all, pick the fastest mode and warn
         that the deadline cannot be met even by the quickest wash.
    """
    fully_feasible = [e for e in evaluations if e["meets_deadline"] and e["meets_performance"]]
 
    if fully_feasible:
        max_energy = max(e["energy_consumption"] for e in fully_feasible) or 1.0
        max_water = max(e["water_consumption"] for e in fully_feasible) or 1.0
        for e in fully_feasible:
            e["_resource_score"] = (e["energy_consumption"] / max_energy) + (e["water_consumption"] / max_water)
        chosen = min(fully_feasible, key=lambda e: e["_resource_score"])
        reason = (
            f"{chosen['mode']} mode uses the least combined water and energy "
            f"({chosen['water_consumption']}L, {chosen['energy_consumption']}kWh) among modes that finish within "
            f"{deadline_minutes} minutes and meet the minimum performance threshold of "
            f"{min_performance_threshold} (performance score {chosen['performance_score']})."
        )
        return chosen, reason
 
    deadline_ok = [e for e in evaluations if e["meets_deadline"]]
    if deadline_ok:
        chosen = max(deadline_ok, key=lambda e: e["performance_score"])
        reason = (
            f"No mode met both the deadline and the minimum performance threshold of "
            f"{min_performance_threshold}; {chosen['mode']} mode was chosen as the best available "
            f"cleaning performance (score {chosen['performance_score']}) that still finishes within "
            f"{deadline_minutes} minutes."
        )
        return chosen, reason
 
    chosen = min(evaluations, key=lambda e: e["cycle_duration_minutes"])
    reason = (
        f"No mode can finish within the {deadline_minutes}-minute deadline; {chosen['mode']} mode is the "
        f"fastest available option ({chosen['cycle_duration_minutes']} minutes) but will still run over."
    )
    return chosen, reason
 