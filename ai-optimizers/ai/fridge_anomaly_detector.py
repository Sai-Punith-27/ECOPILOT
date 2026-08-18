"""
fridge_anomaly_detector.py
----------------------------
Standalone refrigerator energy anomaly detector for EcoPilot.
 
Given live sensor readings and a historical average power baseline, this
module estimates how much of the refrigerator's current power draw is
"explained" by known, benign factors (frequent door opening, high ambient
temperature) versus "unexplained" -- and separately checks whether the
internal temperature is consistent with the power being drawn (a
mismatch there is flagged as an "abnormal cooling pattern").
 
*** THIS IS AN ADVISORY PROTOTYPE, NOT A DIAGNOSTIC TOOL. ***
It NEVER claims to detect, confirm, or diagnose actual hardware failure.
Every output is a simulated, transparent estimate meant to flag "this is
worth a look" -- not "your compressor is broken." Recommendations always
point toward observation, behavior changes, or professional inspection,
never toward a confirmed fault.
 
Design goals:
- Transparent: every number comes from a simple, documented formula.
- Deterministic: same inputs always produce the same output.
- Self-contained: no dependency on the rest of the EcoPilot codebase.
 
DISCLAIMER: The scoring formulas below are simplified engineering
approximations built for a hackathon MVP demo. They are directionally
useful for flagging unusual patterns but are not a certified diagnostic;
treat every output as a SIMULATED estimate.
"""
 
from typing import Dict, List, Tuple
 
# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
 
# --- "Explainable power" model: how much extra power is normal to expect
#     given door openings and ambient heat, before we call anything unusual.
DOOR_OPEN_POWER_FACTOR_PER_OPEN: float = 0.02   # +2% expected power per door open (last period)
AMBIENT_BASELINE_C: float = 25.0                # ambient temp above which extra cooling load is expected
AMBIENT_POWER_FACTOR_PER_DEGREE: float = 0.03   # +3% expected power per degree above baseline
 
# --- Anomaly score weighting (each component capped; combined score clamped to 100) ---
MAX_POWER_SCORE: float = 60.0     # points from raw power excess vs. historical baseline
MAX_TEMP_SCORE: float = 60.0      # points from internal-temperature safe-range mismatch
POWER_SCORE_SENSITIVITY: float = 150.0  # multiplier converting excess ratio -> points
 
# --- Status threshold ---
WARNING_THRESHOLD: float = 40.0
 
# --- Cause-flagging thresholds ---
DOOR_OPEN_CAUSE_THRESHOLD: int = 8       # door openings in the observed period
AMBIENT_CAUSE_THRESHOLD_C: float = 30.0
UNEXPLAINED_EXCESS_CAUSE_RATIO: float = 0.15  # 15% unexplained excess flags a cause
 
# --- Safe internal temperature range (food-safety guidance, illustrative) ---
FRIDGE_SAFE_MIN_C: float = 1.0
FRIDGE_SAFE_MAX_C: float = 4.0
TEMP_MISMATCH_POINTS_PER_DEGREE: float = 10.0
 
 
def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
 
 
# ---------------------------------------------------------------------------
# Core estimators
# ---------------------------------------------------------------------------
 
def estimate_predicted_normal_power(historical_average_power: float, door_open_count: int,
                                     ambient_temperature: float) -> float:
    """
    Deterministic estimate of how much power SHOULD be drawn right now,
    given known benign factors -- more door openings and hotter ambient
    air both legitimately raise compressor duty cycle. Anything drawn
    beyond this predicted figure is treated as "unexplained."
    """
    door_factor = 1.0 + DOOR_OPEN_POWER_FACTOR_PER_OPEN * max(door_open_count, 0)
    ambient_factor = 1.0 + AMBIENT_POWER_FACTOR_PER_DEGREE * max(ambient_temperature - AMBIENT_BASELINE_C, 0.0)
    return round(historical_average_power * door_factor * ambient_factor, 3)
 
 
def estimate_unexplained_excess_ratio(current_power: float, predicted_normal_power: float,
                                       historical_average_power: float) -> float:
    """
    Fraction of historical_average_power that current draw exceeds the
    predicted-normal figure by. Can be negative (drawing less than
    predicted). This is INFORMATIONAL -- it tells you how much of the
    excess is still unexplained after crediting door-opening/ambient
    effects -- but it does NOT gate the anomaly score itself (see
    estimate_raw_excess_ratio for that), so that a genuinely elevated
    power draw still surfaces "high ambient temperature" or "frequent
    door opening" as a likely CAUSE rather than being fully excused by
    the same factor.
    """
    if historical_average_power <= 0:
        return 0.0
    return round((current_power - predicted_normal_power) / historical_average_power, 4)
 
 
def estimate_raw_excess_ratio(current_power: float, historical_average_power: float) -> float:
    """
    Simple, primary anomaly signal: how far current draw is from the
    historical baseline, as a fraction of that baseline. This drives the
    anomaly score directly; door-opening/ambient-temperature/cooling-
    pattern checks are used afterward to explain WHY the excess is
    happening, not to cancel it out of the score.
    """
    if historical_average_power <= 0:
        return 0.0
    return round((current_power - historical_average_power) / historical_average_power, 4)
 
 
def estimate_temp_mismatch_degrees(internal_temperature: float) -> float:
    """
    Degrees outside the safe internal-temperature band (0 if within band).
    Used as a proxy for "the fridge isn't maintaining the temperature you'd
    expect," independent of what the power draw looks like.
    """
    too_warm = max(internal_temperature - FRIDGE_SAFE_MAX_C, 0.0)
    too_cold = max(FRIDGE_SAFE_MIN_C - internal_temperature, 0.0)
    return round(too_warm + too_cold, 3)
 
 
def compute_anomaly_score(raw_excess_ratio: float, temp_mismatch_degrees: float) -> Tuple[float, float, float]:
    """Returns (total_score, power_component, temp_component), each transparent and separately inspectable."""
    power_component = _clamp(raw_excess_ratio * POWER_SCORE_SENSITIVITY, 0.0, MAX_POWER_SCORE)
    temp_component = _clamp(temp_mismatch_degrees * TEMP_MISMATCH_POINTS_PER_DEGREE, 0.0, MAX_TEMP_SCORE)
    total = round(_clamp(power_component + temp_component, 0.0, 100.0), 2)
    return total, round(power_component, 2), round(temp_component, 2)
 
 
# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------
 
def detect_anomaly(
    internal_temperature: float,
    ambient_temperature: float,
    door_open_count: int,
    current_power: float,
    historical_average_power: float,
    warning_threshold: float = WARNING_THRESHOLD,
) -> Dict:
    """
    Evaluate whether the refrigerator's current power draw looks unusual,
    and if so, suggest likely benign explanations before anything else.
 
    Returns:
        {
          "status": "NORMAL" | "WARNING",
          "anomaly_score": ...,             # 0-100
          "estimated_excess_energy": ...,   # current_power - historical_average_power (can be negative)
          "possible_causes": [...],
          "recommendation": ...,
          "details": {...}                  # full breakdown, for transparency
        }
    """
    predicted_normal_power = estimate_predicted_normal_power(
        historical_average_power, door_open_count, ambient_temperature
    )
    unexplained_excess_ratio = estimate_unexplained_excess_ratio(
        current_power, predicted_normal_power, historical_average_power
    )
    raw_excess_ratio = estimate_raw_excess_ratio(current_power, historical_average_power)
    temp_mismatch_degrees = estimate_temp_mismatch_degrees(internal_temperature)
 
    anomaly_score, power_component, temp_component = compute_anomaly_score(
        raw_excess_ratio, temp_mismatch_degrees
    )
 
    status = "WARNING" if anomaly_score >= warning_threshold else "NORMAL"
 
    possible_causes = _identify_causes(
        door_open_count, ambient_temperature, raw_excess_ratio, temp_mismatch_degrees, status
    )
 
    estimated_excess_energy = round(current_power - historical_average_power, 3)
 
    recommendation = _build_recommendation(status, possible_causes)
 
    return {
        "status": status,
        "anomaly_score": anomaly_score,
        "estimated_excess_energy": estimated_excess_energy,
        "possible_causes": possible_causes,
        "recommendation": recommendation,
        "details": {
            "predicted_normal_power": predicted_normal_power,
            "unexplained_excess_ratio": unexplained_excess_ratio,
            "raw_excess_ratio": raw_excess_ratio,
            "temp_mismatch_degrees": temp_mismatch_degrees,
            "power_score_component": power_component,
            "temp_score_component": temp_component,
        },
    }
 
 
# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
 
def _identify_causes(door_open_count: int, ambient_temperature: float,
                      raw_excess_ratio: float, temp_mismatch_degrees: float,
                      status: str) -> List[str]:
    if status == "NORMAL":
        return []
 
    causes: List[str] = []
 
    if door_open_count >= DOOR_OPEN_CAUSE_THRESHOLD:
        causes.append("frequent door opening")
 
    if ambient_temperature >= AMBIENT_CAUSE_THRESHOLD_C:
        causes.append("high ambient temperature")
 
    # "Abnormal cooling pattern" covers two situations, both advisory-only:
    #  (a) power draw is elevated well beyond the historical baseline with
    #      no other obvious explanation, or
    #  (b) the internal temperature is outside the safe range regardless of
    #      what the power draw looks like (cooling isn't keeping up, or is
    #      overshooting, relative to what's expected).
    if raw_excess_ratio >= UNEXPLAINED_EXCESS_CAUSE_RATIO or temp_mismatch_degrees > 0:
        causes.append("abnormal cooling pattern")
 
    # Fallback: flagged WARNING but none of the specific triggers fired
    # (e.g. threshold customized very low) -- still surface a generic cause
    # rather than returning an empty list for a WARNING status.
    if not causes:
        causes.append("abnormal cooling pattern")
 
    return causes
 
 
def _build_recommendation(status: str, possible_causes: List[str]) -> str:
    if status == "NORMAL":
        return "Power consumption is within the expected range for current conditions. No action needed."
 
    parts = ["Unusual refrigerator energy/cooling behavior detected relative to the expected baseline."]
 
    if "frequent door opening" in possible_causes:
        parts.append("Consider reducing how often and how long the door is left open.")
    if "high ambient temperature" in possible_causes:
        parts.append("Check whether the fridge is exposed to direct sunlight or a nearby heat source, "
                      "and consider improving ventilation around it.")
    if "abnormal cooling pattern" in possible_causes:
        parts.append("Monitor internal temperature over the next few hours; if it stays outside the "
                      "1-4C safe range or power remains elevated, consider a professional inspection.")
 
    parts.append(
        "This is an advisory estimate based on simulated sensor data, not a diagnosis or confirmation "
        "of any hardware fault."
    )
    return " ".join(parts)
 