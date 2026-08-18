"""
ac_optimizer.py
----------------
Standalone AC optimization module for EcoPilot.
 
Given live sensor/state inputs (temperature, humidity, occupancy,
current setpoint, current power draw, outside temperature), this module
evaluates a fixed set of candidate setpoints (22-26C), estimates energy
and comfort for each, and recommends the lowest-energy setpoint that
still satisfies a minimum comfort threshold.
 
Design goals (per spec):
- Transparent: every number is produced by a simple, documented formula
  — no black-box model.
- Deterministic: same inputs always produce the same output. No randomness,
  no hidden state, no external calls.
- Self-contained: no dependency on the rest of the EcoPilot codebase.
 
DISCLAIMER: The energy/comfort formulas below are simplified engineering
approximations built for a hackathon MVP demo. They are directionally
realistic but not lab-measured; treat all outputs as SIMULATED estimates,
not real-world measured savings.
"""
 
from typing import Dict, List, Sequence
 
# ---------------------------------------------------------------------------
# Tunable constants (kept at module level so they're easy to find/adjust)
# ---------------------------------------------------------------------------
 
CANDIDATE_SETPOINTS: Sequence[float] = (22, 23, 24, 25, 26)
 
# Minimum comfort_score (0-100) a setpoint must reach to be considered usable.
DEFAULT_MIN_COMFORT_THRESHOLD: float = 70.0
 
# How strongly a 1C gap between outside temperature and setpoint increases
# compressor load (rule-of-thumb HVAC coefficient, illustrative).
LOAD_FACTOR_PER_DEGREE_GAP: float = 0.05
 
# Baseline (minimum) load factor even at a very small/zero temperature gap
# — the compressor, fans, and electronics still draw some power.
BASE_LOAD_FACTOR: float = 0.30
 
# Extra load per % humidity above 50% (moisture makes the compressor work harder).
HUMIDITY_LOAD_FACTOR_PER_PERCENT: float = 0.01
HUMIDITY_LOAD_THRESHOLD: float = 50.0
 
# Comfort penalty per degree of gap between the setpoint and the actual
# room temperature (bigger gap = setpoint is further from what the room
# currently feels like = lower immediate comfort score).
COMFORT_PENALTY_PER_DEGREE_GAP: float = 8.0
 
# Extra comfort penalty per % humidity above this threshold (high humidity
# feels uncomfortable regardless of temperature).
COMFORT_HUMIDITY_THRESHOLD: float = 60.0
COMFORT_PENALTY_PER_HUMIDITY_PERCENT: float = 0.5
 
 
def _load_factor(setpoint: float, outside_temperature: float, humidity: float) -> float:
    """
    Deterministic, transparent proxy for how hard the compressor has to
    work at a given setpoint. Depends only on the temperature gap between
    outside and setpoint, and on humidity — never on other setpoints, so
    each candidate can be evaluated independently.
    """
    gap = max(outside_temperature - setpoint, 0.0)
    humidity_extra = max(humidity - HUMIDITY_LOAD_THRESHOLD, 0.0) * HUMIDITY_LOAD_FACTOR_PER_PERCENT
    return BASE_LOAD_FACTOR + LOAD_FACTOR_PER_DEGREE_GAP * gap + humidity_extra
 
 
def estimate_energy(setpoint: float, outside_temperature: float, humidity: float,
                     current_setpoint: float, current_power: float) -> float:
    """
    Estimate energy draw at `setpoint`, CALIBRATED against the real,
    sensor-reported `current_power` at `current_setpoint`. This avoids
    inventing a rated-power constant: instead we scale the measured
    current power by the ratio of load factors between the candidate
    setpoint and the current setpoint.
 
        energy(setpoint) = current_power * load_factor(setpoint)
                                          / load_factor(current_setpoint)
 
    This means estimate_energy(current_setpoint, ...) always exactly
    reproduces current_power (self-consistent baseline).
    """
    current_load = _load_factor(current_setpoint, outside_temperature, humidity)
    candidate_load = _load_factor(setpoint, outside_temperature, humidity)
    if current_load <= 0:
        # Defensive fallback; should not happen given BASE_LOAD_FACTOR > 0.
        return round(current_power, 3)
    energy = current_power * (candidate_load / current_load)
    return round(energy, 3)
 
 
def comfort_score(setpoint: float, temperature: float, humidity: float, occupancy: bool) -> float:
    """
    Deterministic comfort score in [0, 100].
 
    - If the room is unoccupied, comfort is not a binding concern, so we
      return a flat 100 for every setpoint — this naturally lets the
      optimizer pick the lowest-energy candidate (highest setpoint)
      when nobody is present.
    - If occupied, comfort decreases the further the candidate setpoint
      is from the room's actual current temperature, and decreases
      further if humidity is high (sticky/uncomfortable air).
    """
    if not occupancy:
        return 100.0
 
    gap = abs(setpoint - temperature)
    score = 100.0 - COMFORT_PENALTY_PER_DEGREE_GAP * gap
 
    if humidity > COMFORT_HUMIDITY_THRESHOLD:
        score -= COMFORT_PENALTY_PER_HUMIDITY_PERCENT * (humidity - COMFORT_HUMIDITY_THRESHOLD)
 
    return round(max(0.0, min(100.0, score)), 2)
 
 
def optimize_ac(temperature: float, humidity: float, occupancy: bool,
                 current_setpoint: float, current_power: float, outside_temperature: float,
                 min_comfort_threshold: float = DEFAULT_MIN_COMFORT_THRESHOLD,
                 candidate_setpoints: Sequence[float] = CANDIDATE_SETPOINTS) -> Dict:
    """
    Evaluate all candidate setpoints and recommend the lowest-energy one
    that still satisfies `min_comfort_threshold`.
 
    Returns a JSON-serializable dict:
        {
          "recommended_setpoint": ...,
          "baseline_energy": ...,
          "optimized_energy": ...,
          "saving_percent": ...,
          "comfort_score": ...,
          "reason": ...
        }
    """
    baseline_energy = estimate_energy(
        current_setpoint, outside_temperature, humidity, current_setpoint, current_power
    )
 
    # --- Evaluate every candidate (transparent, logged for explainability) ---
    evaluations: List[Dict] = []
    for sp in candidate_setpoints:
        energy = estimate_energy(sp, outside_temperature, humidity, current_setpoint, current_power)
        comfort = comfort_score(sp, temperature, humidity, occupancy)
        saving_pct = 0.0 if baseline_energy == 0 else round(
            100 * (baseline_energy - energy) / baseline_energy, 2
        )
        evaluations.append({
            "setpoint": sp,
            "estimated_energy": energy,
            "comfort_score": comfort,
            "energy_saving_percent": saving_pct,
        })
 
    # --- Select: lowest-energy candidate that meets the comfort threshold ---
    feasible = [e for e in evaluations if e["comfort_score"] >= min_comfort_threshold]
 
    if feasible:
        chosen = min(feasible, key=lambda e: e["estimated_energy"])
        if not occupancy:
            reason = (
                f"Room is unoccupied, so comfort is not a limiting factor; "
                f"setpoint {chosen['setpoint']}C was chosen as the lowest-energy option "
                f"among {list(candidate_setpoints)}."
            )
        else:
            reason = (
                f"Setpoint {chosen['setpoint']}C gives the lowest estimated energy "
                f"({chosen['estimated_energy']}) among candidates meeting the minimum "
                f"comfort threshold of {min_comfort_threshold} (comfort score "
                f"{chosen['comfort_score']})."
            )
    else:
        # No candidate meets the threshold -> fall back to the most comfortable
        # option available, and say so explicitly (never silently violate comfort).
        chosen = max(evaluations, key=lambda e: e["comfort_score"])
        reason = (
            f"No candidate setpoint reached the minimum comfort threshold of "
            f"{min_comfort_threshold}; falling back to {chosen['setpoint']}C, the most "
            f"comfortable option available (comfort score {chosen['comfort_score']})."
        )
 
    return {
        "recommended_setpoint": chosen["setpoint"],
        "baseline_energy": baseline_energy,
        "optimized_energy": chosen["estimated_energy"],
        "saving_percent": chosen["energy_saving_percent"],
        "comfort_score": chosen["comfort_score"],
        "reason": reason,
    }
 