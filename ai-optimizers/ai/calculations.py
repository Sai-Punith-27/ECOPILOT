"""
calculations.py
----------------
Pure calculation functions used by the optimizer to estimate energy,
water, cost and carbon figures for each appliance.
 
All formulas here are SIMPLIFIED, TRANSPARENT engineering approximations
built for an SIH (Smart India Hackathon) prototype / MVP. They are meant
to be *directionally realistic* (right order of magnitude, right sign of
effect) and fully explainable line-by-line — not laboratory-grade energy
models. Every simulated number produced by this module should be treated
as an ESTIMATE for demo purposes, not a real-world measured value.
 
Constants (tariff, emission factor, water cost) are illustrative Indian
household averages and should be swapped for real utility data if this
prototype is taken further.
"""
 
from typing import Tuple
 
# ---------------------------------------------------------------------------
# Illustrative constants (override these if you have local/real values)
# ---------------------------------------------------------------------------
 
ELECTRICITY_TARIFF_INR_PER_KWH = 8.0     # avg. Indian household slab rate
WATER_COST_INR_PER_LITER = 0.05          # approx municipal + pumping cost
GRID_EMISSION_FACTOR_KG_CO2_PER_KWH = 0.82  # Indian grid avg (CEA CO2 baseline, illustrative)
 
 
def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
 
 
def compute_cost_inr(energy_kwh: float, water_liters: float) -> float:
    """Total monetary cost of a given amount of energy + water use."""
    return round(
        energy_kwh * ELECTRICITY_TARIFF_INR_PER_KWH
        + water_liters * WATER_COST_INR_PER_LITER,
        2,
    )
 
 
def compute_carbon_kg(energy_kwh: float) -> float:
    """CO2 emissions (kg) attributable to a given amount of electricity."""
    return round(energy_kwh * GRID_EMISSION_FACTOR_KG_CO2_PER_KWH, 3)
 
 
# ---------------------------------------------------------------------------
# Air Conditioner
# ---------------------------------------------------------------------------
 
def ac_energy_kwh(target_temp_c: float, outdoor_temp_c: float,
                   runtime_hours: float, rated_power_kw: float,
                   mode: str = "cool", occupied: bool = True) -> float:
    """
    Simplified AC load model.
 
    Physical intuition:
    - Bigger gap between outdoor and target temperature => compressor
      works harder => higher load factor.
    - Every 1C raise in target temperature reduces compressor duty by
      roughly ~3-4% (well-known HVAC rule of thumb used for demo).
    - 'eco'/'fan' modes cut effective compressor duty further.
    - An unoccupied room still incurs a small standby/fan draw if left on.
    """
    if not occupied:
        # Standby / idle draw only (fan + electronics), not full compressor load
        return round(rated_power_kw * 0.05 * runtime_hours, 3)
 
    temp_gap = max(outdoor_temp_c - target_temp_c, 0)
    base_load_factor = clamp(0.35 + 0.035 * temp_gap, 0.30, 1.15)
 
    mode_multiplier = {
        "cool": 1.0,
        "dehumidify": 0.85,
        "fan": 0.35,
        "eco": 0.80,
    }.get(mode, 1.0)
 
    load_factor = base_load_factor * mode_multiplier
    return round(rated_power_kw * load_factor * runtime_hours, 3)
 
 
# ---------------------------------------------------------------------------
# Refrigerator
# ---------------------------------------------------------------------------
 
def fridge_energy_kwh(target_temp_c: float, ambient_temp_c: float,
                       door_open_seconds_last_hour: float,
                       frost_thickness_mm: float,
                       rated_power_w: float, hours: float = 24.0) -> float:
    """
    Simplified refrigerator load model.
 
    Physical intuition:
    - Lower (colder) setpoint => longer compressor duty cycle.
    - Higher ambient temperature => more heat leaks in => higher duty cycle.
    - Door left open longer => cold air escapes => compressor compensates.
    - Frost buildup acts as insulation on the evaporator, reducing
      efficiency and forcing longer run times (well known refrigeration
      effect) -> modeled as a duty-cycle penalty.
    """
    base_duty = clamp(0.25 + 0.015 * (ambient_temp_c - 25) - 0.02 * (target_temp_c - 4), 0.15, 0.65)
    door_penalty = clamp(door_open_seconds_last_hour / 3600.0 * 0.20, 0.0, 0.20)
    frost_penalty = clamp(frost_thickness_mm * 0.01, 0.0, 0.25)
 
    duty_cycle = clamp(base_duty + door_penalty + frost_penalty, 0.15, 0.95)
    power_kw = rated_power_w / 1000.0
    return round(power_kw * duty_cycle * hours, 3)
 
 
# ---------------------------------------------------------------------------
# Washing Machine
# ---------------------------------------------------------------------------
 
def washing_machine_energy_kwh(rated_power_w: float, cycle_minutes: float,
                                water_temp_c: float) -> float:
    """
    Energy = rated draw * time, with a heating surcharge if the water is
    heated above ambient (hot-wash cycles draw noticeably more power due
    to the heating element).
    """
    power_kw = rated_power_w / 1000.0
    base_energy = power_kw * (cycle_minutes / 60.0)
 
    if water_temp_c >= 60:
        heat_surcharge = 0.9   # hot wash roughly ~1.9x baseline drum energy
    elif water_temp_c >= 40:
        heat_surcharge = 0.4
    else:
        heat_surcharge = 0.0
 
    return round(base_energy * (1 + heat_surcharge), 3)
 
 
def washing_machine_water_liters(load_weight_kg: float, max_capacity_kg: float,
                                  water_per_kg_liters: float, full_load_mode: bool) -> float:
    """
    Water use model.
    - Full-load mode: water scales efficiently with actual load weight.
    - Non full-load (i.e. running a small load on a default/large-load
      water level) wastes water because most machines still fill to a
      near-fixed level regardless of a small load, unless the user
      selects a proper load-size / eco setting.
    """
    if full_load_mode:
        return round(load_weight_kg * water_per_kg_liters, 2)
    else:
        # Assume machine fills for close to max capacity regardless of load
        return round(max_capacity_kg * water_per_kg_liters, 2)
 
 
# ---------------------------------------------------------------------------
# Desert Air Cooler
# ---------------------------------------------------------------------------
 
def air_cooler_energy_kwh(fan_speed: int, rated_power_w: float, runtime_hours: float) -> float:
    """Cooler energy is dominated by fan motor speed (roughly linear)."""
    power_kw = rated_power_w / 1000.0
    speed_factor = clamp(fan_speed / 5.0, 0.2, 1.0)
    return round(power_kw * speed_factor * runtime_hours, 3)
 
 
def air_cooler_water_liters(pad_wetness_percent: float, runtime_hours: float,
                             humidity_percent: float, evaporative_active: bool) -> float:
    """
    Water evaporation model.
    - Higher pad wetness target + longer runtime => more water evaporated.
    - High ambient humidity reduces evaporation efficiency, meaning water
      is still drawn/pumped but cooling benefit is poor -> wasteful.
    - If evaporative cooling is switched off (pure fan mode), water use
      drops to ~0.
    """
    if not evaporative_active:
        return 0.0
 
    base_rate_lph = 0.9  # liters/hour at 100% pad wetness, moderate humidity, baseline
    humidity_penalty = clamp(1 + (humidity_percent - 40) / 100.0, 0.6, 1.4)
    usage = base_rate_lph * (pad_wetness_percent / 100.0) * humidity_penalty * runtime_hours
    return round(max(usage, 0.0), 2)