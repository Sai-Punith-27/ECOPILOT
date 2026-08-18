EcoPilot — AI / Optimization Module

This folder is a standalone Python module implementing the AI/optimization logic for EcoPilot's SIH prototype. It has no dependency on and does not touch the frontend, FastAPI backend, or MQTT layer — those are other teams' modules. You can import this package from anywhere (CLI, notebook, backend handler, MQTT callback) and call one function per appliance.

Covers 4 appliances:

Air Conditioner (ACSensorData)
Refrigerator (RefrigeratorSensorData)
Washing Machine (WashingMachineSensorData)
Desert Air Cooler (AirCoolerSensorData)
⚠️ Important disclaimer

All sensor data, energy/water formulas, and savings figures in this module are SIMULATED for demo/prototype purposes. The physics-based formulas in calculations.py are simplified, transparent approximations designed to be directionally realistic and fully explainable — they are not laboratory- or utility-grade measurements. Nothing produced by this module should be presented as a real-world measured saving. If this prototype moves past the hackathon stage, these formulas should be calibrated against real appliance datasheets and metered data.

Files
File	Purpose
models.py	Plain dataclasses for sensor inputs, constraints, and the output result. No external dependencies.
calculations.py	Pure functions computing energy (kWh), water (liters), cost (INR), and carbon (kg CO2) for each appliance. All constants and formulas documented inline.
optimizer.py	EcoPilotOptimizer — the rule-based + weighted-scoring optimizer. One optimize_<appliance>() method per appliance, plus a generic optimize(appliance_type, data) dispatcher.
test_optimizer.py	16 unit tests covering normal behavior, edge cases, and constraint enforcement for all 4 appliances.
README.md	This file.

No third-party packages are required — everything runs on the Python 3 standard library (dataclasses, enum, typing, unittest).

How the optimizer works

The objective, as specified, is:

minimize:   energy + water + cost + carbon
subject to: comfort, appliance performance, safety

This is implemented as a transparent rule-based + weighted-scoring search, not a black-box model, so every recommendation can be explained in plain language:

Generate candidates. For each appliance, a small set of candidate actions is generated from domain rules (e.g. "room unoccupied → turn off", "setpoint colder than needed → raise it", "humidity too high for evaporative cooling → switch to fan-only"). The set always includes a no_change baseline candidate.
Enforce constraints (filter). Any candidate that would violate a comfort, performance, or safety constraint (ComfortSafetyConstraints in models.py) is discarded before scoring — e.g. the AC will never be pushed outside its comfort band, the fridge will never be pushed outside the food-safety temperature range, the washing machine cycle will never be shortened below a safety/performance floor, and the desert cooler will never run evaporative cooling on a near-empty tank.
Score remaining candidates. Each feasible candidate is scored with a weighted objective:
   score = w_energy * (energy / baseline_energy)
         + w_water  * (water  / baseline_water)
         + w_cost   * (cost   / baseline_cost)
         + w_carbon * (carbon / baseline_carbon)

Values are normalized against the baseline so the four objectives (kWh, liters, INR, kg CO2 — all different units/scales) are comparable. Default weights (OPTIMIZATION_WEIGHTS in optimizer.py):

python
   {"energy": 0.35, "water": 0.25, "cost": 0.20, "carbon": 0.20}

Weights and constraints are both injectable via the EcoPilotOptimizer constructor, so a hackathon demo can tune them live without touching the algorithm.

Pick the lowest-scoring feasible candidate and return baseline vs. optimized energy/water/cost/carbon, the estimated saving, and a human-readable explanation of exactly which rule fired and why.

This keeps "optimization" a genuine (if small) search over explainable, constrained candidates — rather than a single hardcoded if/else path.

Known simplification

Candidates currently represent one change at a time (e.g. "lower wash temperature" OR "use load-size water setting"), not combinations. A natural next step post-MVP is to let the candidate generator compose multiple compatible actions (e.g. lower temperature and use the load-size setting together) and score the combined effect.

Usage
python
from models import ACSensorData
from optimizer import EcoPilotOptimizer

optimizer = EcoPilotOptimizer()  # default weights + default constraints

reading = ACSensorData(
    current_temp_c=24,
    target_temp_c=20,
    outdoor_temp_c=39,
    humidity_percent=55,
    room_occupied=True,
    minutes_since_last_motion=2,
    mode="cool",
)

result = optimizer.optimize_ac(reading)
print(result.recommended_action)
print(result.explanation)
print(result.to_dict())   # JSON-serializable dict, ready for an API/frontend to consume

Generic dispatch (useful if a caller only has an ApplianceType + raw dict):

python
from models import ApplianceType, RefrigeratorSensorData
from optimizer import EcoPilotOptimizer

optimizer = EcoPilotOptimizer()
data = RefrigeratorSensorData(
    internal_temp_c=2, target_temp_c=2, ambient_temp_c=33,
    door_open_count_last_hour=9, door_open_total_seconds_last_hour=420,
    frost_thickness_mm=5,
)
result = optimizer.optimize(ApplianceType.REFRIGERATOR, data)
Sample output (simulated)
json
{
  "appliance": "refrigerator",
  "recommended_action": "Run defrost cycle to remove frost buildup",
  "baseline_energy_kwh": 1.74,
  "optimized_energy_kwh": 1.56,
  "baseline_water_liters": 0.0,
  "optimized_water_liters": 0.0,
  "estimated_cost_saving_inr": 1.44,
  "estimated_carbon_reduction_kg": 0.148,
  "explanation": "Frost thickness is 5.0mm, which insulates the evaporator and forces longer compressor run times. Defrosting restores heat-transfer efficiency. Estimated energy change: 10.3% vs baseline (simulated).",
  "warnings": []
}
Running the tests
bash
cd ai
python -m unittest test_optimizer.py -v

16 tests, all passing, covering (per appliance):

A normal optimization scenario with a measurable saving
At least one constraint/safety edge case (never violated even if "cheaper")
Result-shape checks (non-empty explanation, correct appliance tag, etc.)
Assumptions & constants (all illustrative, override as needed)

Defined in calculations.py:

Constant	Value	Note
ELECTRICITY_TARIFF_INR_PER_KWH	8.0	Approx. Indian household slab rate
WATER_COST_INR_PER_LITER	0.05	Approx. municipal + pumping cost
GRID_EMISSION_FACTOR_KG_CO2_PER_KWH	0.82	Indian grid average (illustrative)

Comfort / safety bounds, defined in models.ComfortSafetyConstraints:

Constraint	Default
AC comfort band	22–28°C
Refrigerator safe food-storage band	1–4°C
Washing machine minimum cycle length	15 minutes
Air cooler minimum tank level for evaporative mode	15%

All of these are constructor parameters / dataclass defaults — change them in one place to match real appliance specs when available.

Extending to a new appliance
Add a sensor dataclass to models.py.
Add energy/water calculation function(s) to calculations.py.
Add an optimize_<appliance>() method to EcoPilotOptimizer following the existing pattern: build candidates → filter by constraints → score → pick best → explain.
Add it to the optimize() dispatcher and ApplianceType enum.
Add tests to test_optimizer.py.