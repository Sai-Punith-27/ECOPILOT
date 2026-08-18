"""
models.py
----------
Data models for the EcoPilot AI / Optimization module.
 
These are plain Python dataclasses with NO external dependencies
(no pydantic, no FastAPI) so this module can be dropped into any
part of the EcoPilot codebase (CLI, notebook, backend service,
MQTT handler, etc.) without coupling to a particular framework.
 
IMPORTANT: All sensor values used in tests/demo are SIMULATED.
This module does not claim any real-world measured savings.
"""
 
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any
 
 
class ApplianceType(Enum):
    AC = "air_conditioner"
    REFRIGERATOR = "refrigerator"
    WASHING_MACHINE = "washing_machine"
    AIR_COOLER = "desert_air_cooler"
 
 
# ---------------------------------------------------------------------------
# Appliance-specific sensor input models
# ---------------------------------------------------------------------------
 
@dataclass
class ACSensorData:
    current_temp_c: float
    target_temp_c: float
    outdoor_temp_c: float
    humidity_percent: float
    room_occupied: bool
    minutes_since_last_motion: float
    mode: str = "cool"                 # cool | dehumidify | fan | eco
    rated_power_kw: float = 1.5
    runtime_hours_today: float = 6.0   # how long the unit has been / will be run
 
 
@dataclass
class RefrigeratorSensorData:
    internal_temp_c: float
    target_temp_c: float
    ambient_temp_c: float
    door_open_count_last_hour: int
    door_open_total_seconds_last_hour: float
    frost_thickness_mm: float
    rated_power_w: float = 150.0
    compressor_duty_cycle_percent: float = 40.0
 
 
@dataclass
class WashingMachineSensorData:
    load_weight_kg: float
    max_capacity_kg: float
    water_temp_c: float
    soil_level: str            # low | medium | high
    fabric_type: str           # cotton | synthetic | delicate | mixed
    selected_cycle_minutes: float
    rated_power_w: float = 500.0
    water_per_kg_liters: float = 15.0   # baseline water use per kg of rated capacity
 
 
@dataclass
class AirCoolerSensorData:
    room_temp_c: float
    outdoor_temp_c: float
    humidity_percent: float
    water_tank_level_percent: float
    fan_speed: int              # 1 (low) - 5 (high)
    pad_wetness_percent: float  # how saturated the cooling pad currently is
    rated_power_w: float = 200.0
    runtime_hours_today: float = 6.0
 
 
# ---------------------------------------------------------------------------
# Constraint configuration (comfort / safety / performance bounds)
# ---------------------------------------------------------------------------
 
@dataclass
class ComfortSafetyConstraints:
    """
    Defines the acceptable operating envelope for each appliance.
    The optimizer will NEVER recommend an action that violates these
    bounds, even if it looks cheaper on paper. This is what keeps the
    "optimization" honest and safe rather than purely cost-minimizing.
    """
    # AC comfort band
    ac_min_target_c: float = 22.0
    ac_max_target_c: float = 28.0
 
    # Refrigerator food-safety band (FSSAI / general guidance: <= 4C)
    fridge_min_safe_c: float = 1.0
    fridge_max_safe_c: float = 4.0
 
    # Washing machine minimum viable cycle time (safety/performance floor)
    wash_min_cycle_minutes: float = 15.0
 
    # Air cooler minimum tank level to allow evaporative operation safely
    cooler_min_tank_percent: float = 15.0
 
 
# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------
 
@dataclass
class OptimizationResult:
    appliance: str
    recommended_action: str
    baseline_energy_kwh: float
    optimized_energy_kwh: float
    baseline_water_liters: float
    optimized_water_liters: float
    estimated_cost_saving_inr: float
    estimated_carbon_reduction_kg: float
    explanation: str
    candidate_scores: Optional[Dict[str, float]] = None
    warnings: Optional[List[str]] = None
 
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d