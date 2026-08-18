"""
optimizer.py
------------
EcoPilot AI / Optimization module.
 
Approach
========
This is a TRANSPARENT, rule-based + weighted-scoring optimizer.
No black-box ML / deep learning is used, by design, so every
recommendation can be explained in plain language.
 
For each appliance the optimizer:
 
1. Generates a small set of CANDIDATE actions using domain rules
   (e.g. "raise AC setpoint by 2C", "switch to fan-only mode",
   "run cooler on fan-only because humidity is too high", ...).
   The candidate set always includes a "no_change" baseline action.
 
2. Filters out any candidate that would violate comfort / safety /
   performance constraints (models.ComfortSafetyConstraints).
 
3. Scores every remaining candidate with a weighted objective:
 
       score = w_energy * norm(energy)
             + w_water  * norm(water)
             + w_cost   * norm(cost)
             + w_carbon * norm(carbon)
 
   where norm() scales each quantity relative to the baseline so the
   four objectives are comparable, and the weights are configurable
   (see OPTIMIZATION_WEIGHTS below).
 
4. Picks the lowest-scoring FEASIBLE candidate as the recommendation
   and reports baseline vs optimized energy/water/cost/carbon plus a
   plain-language explanation of exactly which rule(s) fired and why.
 
This keeps the "optimization" step genuinely a search over explainable
candidates rather than a hardcoded if/else -> single answer.
 
Disclaimer
==========
All appliance inputs used in demos/tests are SIMULATED sensor data.
Nothing in this module should be presented as a real-world measured
energy/water saving.
"""
 
from typing import List, Dict, Tuple, Optional, Any
 
from models import (
    ApplianceType,
    ACSensorData,
    RefrigeratorSensorData,
    WashingMachineSensorData,
    AirCoolerSensorData,
    ComfortSafetyConstraints,
    OptimizationResult,
)
from calculations import (
    ac_energy_kwh,
    fridge_energy_kwh,
    washing_machine_energy_kwh,
    washing_machine_water_liters,
    air_cooler_energy_kwh,
    air_cooler_water_liters,
    compute_cost_inr,
    compute_carbon_kg,
)
 
# Default weights for the multi-objective score.
# Sum need not be 1.0 -- they are relative importances.
OPTIMIZATION_WEIGHTS = {
    "energy": 0.35,
    "water": 0.25,
    "cost": 0.20,
    "carbon": 0.20,
}
 
 
def _normalize(value: float, baseline: float) -> float:
    """Scale a raw quantity relative to its baseline so objectives with
    very different units/magnitudes (kWh vs liters vs INR vs kgCO2) can
    be combined in one weighted score. Returns 1.0 for "no change"."""
    if baseline <= 0:
        return 0.0
    return value / baseline
 
 
def _weighted_score(energy, water, cost, carbon,
                     base_energy, base_water, base_cost, base_carbon,
                     weights: Dict[str, float]) -> float:
    return (
        weights["energy"] * _normalize(energy, base_energy)
        + weights["water"] * _normalize(water, base_water)
        + weights["cost"] * _normalize(cost, base_cost)
        + weights["carbon"] * _normalize(carbon, base_carbon)
    )
 
 
class EcoPilotOptimizer:
    """
    Main entry point for the AI/optimization module.
 
    Usage:
        optimizer = EcoPilotOptimizer()
        result = optimizer.optimize_ac(ac_sensor_data)
        result = optimizer.optimize_refrigerator(fridge_sensor_data)
        result = optimizer.optimize_washing_machine(wm_sensor_data)
        result = optimizer.optimize_air_cooler(cooler_sensor_data)
 
    Or, generically:
        result = optimizer.optimize(ApplianceType.AC, ac_sensor_data)
    """
 
    def __init__(self,
                 weights: Optional[Dict[str, float]] = None,
                 constraints: Optional[ComfortSafetyConstraints] = None):
        self.weights = weights or OPTIMIZATION_WEIGHTS
        self.constraints = constraints or ComfortSafetyConstraints()
 
    # ------------------------------------------------------------------
    # Generic dispatcher
    # ------------------------------------------------------------------
 
    def optimize(self, appliance: ApplianceType, data: Any) -> OptimizationResult:
        dispatch = {
            ApplianceType.AC: self.optimize_ac,
            ApplianceType.REFRIGERATOR: self.optimize_refrigerator,
            ApplianceType.WASHING_MACHINE: self.optimize_washing_machine,
            ApplianceType.AIR_COOLER: self.optimize_air_cooler,
        }
        if appliance not in dispatch:
            raise ValueError(f"Unsupported appliance type: {appliance}")
        return dispatch[appliance](data)
 
    # ------------------------------------------------------------------
    # Air Conditioner
    # ------------------------------------------------------------------
 
    def optimize_ac(self, data: ACSensorData) -> OptimizationResult:
        c = self.constraints
        warnings: List[str] = []
 
        # ---- Baseline: current settings, as-is ----
        base_energy = ac_energy_kwh(
            data.target_temp_c, data.outdoor_temp_c, data.runtime_hours_today,
            data.rated_power_kw, data.mode, occupied=True,  # baseline assumes it's actually running
        )
        base_water = 0.0  # AC does not directly consume water in this model
        base_cost = compute_cost_inr(base_energy, base_water)
        base_carbon = compute_carbon_kg(base_energy)
 
        # ---- Build candidates ----
        candidates: Dict[str, Dict[str, float]] = {}
 
        # 1. No change
        candidates["no_change"] = dict(
            target_temp=data.target_temp_c, mode=data.mode, occupied_run=True,
        )
 
        # 2. Room unoccupied for a while -> suggest turning off / standby
        if not data.room_occupied and data.minutes_since_last_motion >= 15:
            candidates["turn_off_unoccupied"] = dict(
                target_temp=data.target_temp_c, mode=data.mode, occupied_run=False,
            )
 
        # 3. Setpoint is colder than the comfortable/efficient band -> raise it.
        #    If it's below the comfort band entirely, jump straight to the
        #    minimum comfortable/efficient setpoint (feasibility fix); otherwise
        #    nudge it up by 2C within the band.
        if data.target_temp_c < c.ac_min_target_c:
            candidates["raise_to_min_comfort"] = dict(
                target_temp=c.ac_min_target_c, mode=data.mode, occupied_run=True,
            )
        elif data.target_temp_c < c.ac_min_target_c + 2:
            raised = min(data.target_temp_c + 2, c.ac_max_target_c)
            if raised > data.target_temp_c:
                candidates["raise_setpoint_2c"] = dict(
                    target_temp=raised, mode=data.mode, occupied_run=True,
                )
 
        # 4. High humidity -> dehumidify mode can feel equally comfortable at
        #    a slightly higher setpoint while using less compressor energy
        if data.humidity_percent >= 60 and data.mode == "cool":
            candidates["switch_to_dehumidify"] = dict(
                target_temp=data.target_temp_c, mode="dehumidify", occupied_run=True,
            )
 
        # 5. eco mode as a general-purpose reduced-load candidate
        if data.mode not in ("eco", "fan"):
            candidates["switch_to_eco"] = dict(
                target_temp=data.target_temp_c, mode="eco", occupied_run=True,
            )
 
        # ---- Evaluate + filter candidates ----
        scored = {}
        details = {}
        for name, params in candidates.items():
            if not (c.ac_min_target_c <= params["target_temp"] <= c.ac_max_target_c):
                continue  # violates comfort constraint, discard
            energy = ac_energy_kwh(
                params["target_temp"], data.outdoor_temp_c, data.runtime_hours_today,
                data.rated_power_kw, params["mode"], occupied=params["occupied_run"],
            )
            water = 0.0
            cost = compute_cost_inr(energy, water)
            carbon = compute_carbon_kg(energy)
            score = _weighted_score(energy, water, cost, carbon,
                                     base_energy, base_water or 1e-9, base_cost, base_carbon,
                                     self.weights)
            scored[name] = score
            details[name] = dict(energy=energy, water=water, cost=cost, carbon=carbon, params=params)
 
        best_name = min(scored, key=scored.get)
        best = details[best_name]
 
        explanation = self._explain_ac(data, best_name, best, base_energy)
 
        return OptimizationResult(
            appliance=ApplianceType.AC.value,
            recommended_action=self._ac_action_label(best_name, best["params"]),
            baseline_energy_kwh=base_energy,
            optimized_energy_kwh=best["energy"],
            baseline_water_liters=base_water,
            optimized_water_liters=best["water"],
            estimated_cost_saving_inr=round(base_cost - best["cost"], 2),
            estimated_carbon_reduction_kg=round(base_carbon - best["carbon"], 3),
            explanation=explanation,
            candidate_scores=scored,
            warnings=warnings,
        )
 
    def _ac_action_label(self, name: str, params: Dict) -> str:
        labels = {
            "no_change": "Keep current AC settings",
            "turn_off_unoccupied": "Turn off AC (room unoccupied)",
            "raise_setpoint_2c": f"Raise AC setpoint to {params['target_temp']:.0f}C",
            "raise_to_min_comfort": f"Raise AC setpoint to {params['target_temp']:.0f}C (was outside the comfortable/efficient band)",
            "switch_to_dehumidify": "Switch AC to dehumidify mode",
            "switch_to_eco": "Switch AC to eco mode",
        }
        return labels.get(name, name)
 
    def _explain_ac(self, data: ACSensorData, best_name: str, best: Dict, base_energy: float) -> str:
        reasons = []
        if best_name == "turn_off_unoccupied":
            reasons.append(
                f"No motion detected for {data.minutes_since_last_motion:.0f} minutes "
                f"and room is marked unoccupied, so continuing full cooling wastes energy."
            )
        elif best_name == "raise_to_min_comfort":
            reasons.append(
                f"Current setpoint ({data.target_temp_c:.0f}C) is below the "
                f"{self.constraints.ac_min_target_c:.0f}-{self.constraints.ac_max_target_c:.0f}C "
                f"comfortable/efficient band; raising it to {self.constraints.ac_min_target_c:.0f}C cuts unnecessary "
                f"compressor duty cycle while staying comfortable."
            )
        elif best_name == "raise_setpoint_2c":
            reasons.append(
                f"Current setpoint ({data.target_temp_c:.0f}C) is colder than necessary for comfort; "
                f"raising it toward the {self.constraints.ac_min_target_c:.0f}-{self.constraints.ac_max_target_c:.0f}C "
                f"efficient comfort band cuts compressor duty cycle."
            )
        elif best_name == "switch_to_dehumidify":
            reasons.append(
                f"Humidity is high ({data.humidity_percent:.0f}%); dehumidify mode removes moisture "
                f"(which drives perceived heat) using less compressor energy than straight cooling."
            )
        elif best_name == "switch_to_eco":
            reasons.append("Eco mode reduces compressor duty cycle while keeping the room within the comfort band.")
        else:
            reasons.append("Current settings are already close to optimal given occupancy and outdoor conditions.")
 
        saving_pct = 0 if base_energy == 0 else round(100 * (base_energy - best["energy"]) / base_energy, 1)
        reasons.append(f"Estimated energy change: {saving_pct}% vs baseline (simulated).")
        return " ".join(reasons)
 
    # ------------------------------------------------------------------
    # Refrigerator
    # ------------------------------------------------------------------
 
    def optimize_refrigerator(self, data: RefrigeratorSensorData) -> OptimizationResult:
        c = self.constraints
        warnings: List[str] = []
 
        base_energy = fridge_energy_kwh(
            data.target_temp_c, data.ambient_temp_c,
            data.door_open_total_seconds_last_hour, data.frost_thickness_mm,
            data.rated_power_w,
        )
        base_water = 0.0
        base_cost = compute_cost_inr(base_energy, base_water)
        base_carbon = compute_carbon_kg(base_energy)
 
        candidates: Dict[str, Dict[str, float]] = {
            "no_change": dict(target_temp=data.target_temp_c, frost=data.frost_thickness_mm),
        }
 
        # 1. Over-cooled: setpoint colder than needed for food safety -> raise toward safe upper bound
        if data.target_temp_c < c.fridge_min_safe_c:
            candidates["raise_to_safe_min"] = dict(target_temp=c.fridge_min_safe_c, frost=data.frost_thickness_mm)
        elif data.target_temp_c < (c.fridge_min_safe_c + c.fridge_max_safe_c) / 2:
            raised = min(data.target_temp_c + 1, c.fridge_max_safe_c)
            candidates["raise_setpoint_1c"] = dict(target_temp=raised, frost=data.frost_thickness_mm)
 
        # 2. Frost buildup -> recommend defrost (frost penalty removed in the "after" estimate)
        if data.frost_thickness_mm >= 3:
            candidates["defrost_now"] = dict(target_temp=data.target_temp_c, frost=0.0)
 
        # 3. Excess door opening -> behavioural nudge (does not change temp/frost directly,
        #    but we still surface it as a zero-cost, zero-risk action if nothing else applies)
        if data.door_open_count_last_hour >= 8 and "no_change" == list(candidates.keys())[-1]:
            candidates["reduce_door_openings"] = dict(target_temp=data.target_temp_c, frost=data.frost_thickness_mm)
 
        scored = {}
        details = {}
        for name, params in candidates.items():
            if not (c.fridge_min_safe_c <= params["target_temp"] <= c.fridge_max_safe_c):
                continue  # food-safety violation, discard
            energy = fridge_energy_kwh(
                params["target_temp"], data.ambient_temp_c,
                data.door_open_total_seconds_last_hour, params["frost"],
                data.rated_power_w,
            )
            water = 0.0
            cost = compute_cost_inr(energy, water)
            carbon = compute_carbon_kg(energy)
            score = _weighted_score(energy, water, cost, carbon,
                                     base_energy, base_water or 1e-9, base_cost, base_carbon,
                                     self.weights)
            scored[name] = score
            details[name] = dict(energy=energy, water=water, cost=cost, carbon=carbon, params=params)
 
        best_name = min(scored, key=scored.get)
        best = details[best_name]
 
        if data.frost_thickness_mm >= 6:
            warnings.append("Frost thickness is significant (>=6mm); schedule defrost soon to protect efficiency and food safety.")
 
        explanation = self._explain_fridge(data, best_name, best, base_energy)
 
        return OptimizationResult(
            appliance=ApplianceType.REFRIGERATOR.value,
            recommended_action=self._fridge_action_label(best_name, best["params"]),
            baseline_energy_kwh=base_energy,
            optimized_energy_kwh=best["energy"],
            baseline_water_liters=base_water,
            optimized_water_liters=best["water"],
            estimated_cost_saving_inr=round(base_cost - best["cost"], 2),
            estimated_carbon_reduction_kg=round(base_carbon - best["carbon"], 3),
            explanation=explanation,
            candidate_scores=scored,
            warnings=warnings,
        )
 
    def _fridge_action_label(self, name: str, params: Dict) -> str:
        labels = {
            "no_change": "Keep current refrigerator settings",
            "raise_to_safe_min": f"Raise setpoint to {params['target_temp']:.1f}C (still within safe food storage range)",
            "raise_setpoint_1c": f"Raise setpoint to {params['target_temp']:.1f}C",
            "defrost_now": "Run defrost cycle to remove frost buildup",
            "reduce_door_openings": "Reduce frequency/duration of door openings",
        }
        return labels.get(name, name)
 
    def _explain_fridge(self, data: RefrigeratorSensorData, best_name: str, best: Dict, base_energy: float) -> str:
        reasons = []
        if best_name in ("raise_to_safe_min", "raise_setpoint_1c"):
            reasons.append(
                f"Setpoint ({data.target_temp_c:.1f}C) is colder than needed; raising it toward "
                f"{best['params']['target_temp']:.1f}C still keeps food within the "
                f"{self.constraints.fridge_min_safe_c:.0f}-{self.constraints.fridge_max_safe_c:.0f}C safe range "
                f"while reducing compressor duty cycle."
            )
        elif best_name == "defrost_now":
            reasons.append(
                f"Frost thickness is {data.frost_thickness_mm:.1f}mm, which insulates the evaporator and forces "
                f"longer compressor run times. Defrosting restores heat-transfer efficiency."
            )
        elif best_name == "reduce_door_openings":
            reasons.append(
                f"Door was opened {data.door_open_count_last_hour} times "
                f"({data.door_open_total_seconds_last_hour:.0f}s total) in the last hour, letting cold air escape "
                f"and increasing compressor duty; fewer/shorter openings reduce this load."
            )
        else:
            reasons.append("Current setpoint and frost level are already close to optimal for safe, efficient operation.")
 
        saving_pct = 0 if base_energy == 0 else round(100 * (base_energy - best["energy"]) / base_energy, 1)
        reasons.append(f"Estimated energy change: {saving_pct}% vs baseline (simulated).")
        return " ".join(reasons)
 
    # ------------------------------------------------------------------
    # Washing Machine
    # ------------------------------------------------------------------
 
    def optimize_washing_machine(self, data: WashingMachineSensorData) -> OptimizationResult:
        c = self.constraints
        warnings: List[str] = []
 
        load_ratio = data.load_weight_kg / data.max_capacity_kg if data.max_capacity_kg else 1.0
        base_full_load_mode = load_ratio >= 0.75  # assume user hasn't selected eco/load-size setting by default
 
        base_energy = washing_machine_energy_kwh(data.rated_power_w, data.selected_cycle_minutes, data.water_temp_c)
        base_water = washing_machine_water_liters(
            data.load_weight_kg, data.max_capacity_kg, data.water_per_kg_liters, full_load_mode=base_full_load_mode
        )
        base_cost = compute_cost_inr(base_energy, base_water)
        base_carbon = compute_carbon_kg(base_energy)
 
        candidates: Dict[str, Dict[str, float]] = {
            "no_change": dict(
                cycle_minutes=data.selected_cycle_minutes, water_temp=data.water_temp_c,
                full_load_mode=base_full_load_mode,
            ),
        }
 
        # 1. Underloaded and machine defaults to a large-load water fill -> use load-size/eco setting
        if load_ratio < 0.75:
            candidates["use_load_size_setting"] = dict(
                cycle_minutes=data.selected_cycle_minutes, water_temp=data.water_temp_c,
                full_load_mode=True,  # water now scales to actual (smaller) load
            )
 
        # 2. Water heated more than the soil level requires -> use cold/warm wash
        if data.water_temp_c >= 40 and data.soil_level in ("low", "medium"):
            candidates["lower_wash_temperature"] = dict(
                cycle_minutes=data.selected_cycle_minutes, water_temp=30.0,
                full_load_mode=base_full_load_mode,
            )
 
        # 3. Light soil with a long cycle selected -> shorten cycle (respect minimum floor)
        if data.soil_level == "low" and data.selected_cycle_minutes > c.wash_min_cycle_minutes:
            shortened = max(c.wash_min_cycle_minutes, data.selected_cycle_minutes - 15)
            if shortened < data.selected_cycle_minutes:
                candidates["shorten_cycle"] = dict(
                    cycle_minutes=shortened, water_temp=data.water_temp_c,
                    full_load_mode=base_full_load_mode,
                )
 
        scored = {}
        details = {}
        for name, params in candidates.items():
            if params["cycle_minutes"] < c.wash_min_cycle_minutes:
                continue  # performance floor violated, discard
            energy = washing_machine_energy_kwh(data.rated_power_w, params["cycle_minutes"], params["water_temp"])
            water = washing_machine_water_liters(
                data.load_weight_kg, data.max_capacity_kg, data.water_per_kg_liters,
                full_load_mode=params["full_load_mode"],
            )
            cost = compute_cost_inr(energy, water)
            carbon = compute_carbon_kg(energy)
            score = _weighted_score(energy, water, cost, carbon,
                                     base_energy, base_water, base_cost, base_carbon,
                                     self.weights)
            scored[name] = score
            details[name] = dict(energy=energy, water=water, cost=cost, carbon=carbon, params=params)
 
        best_name = min(scored, key=scored.get)
        best = details[best_name]
 
        if load_ratio < 0.3:
            warnings.append("Load is very small relative to machine capacity; consider waiting for a fuller load if possible.")
 
        explanation = self._explain_wm(data, load_ratio, best_name, best, base_energy, base_water)
 
        return OptimizationResult(
            appliance=ApplianceType.WASHING_MACHINE.value,
            recommended_action=self._wm_action_label(best_name, best["params"]),
            baseline_energy_kwh=base_energy,
            optimized_energy_kwh=best["energy"],
            baseline_water_liters=base_water,
            optimized_water_liters=best["water"],
            estimated_cost_saving_inr=round(base_cost - best["cost"], 2),
            estimated_carbon_reduction_kg=round(base_carbon - best["carbon"], 3),
            explanation=explanation,
            candidate_scores=scored,
            warnings=warnings,
        )
 
    def _wm_action_label(self, name: str, params: Dict) -> str:
        labels = {
            "no_change": "Keep current wash cycle settings",
            "use_load_size_setting": "Enable load-size/eco water-level setting for this load",
            "lower_wash_temperature": f"Lower wash temperature to {params['water_temp']:.0f}C",
            "shorten_cycle": f"Shorten cycle to {params['cycle_minutes']:.0f} minutes",
        }
        return labels.get(name, name)
 
    def _explain_wm(self, data: WashingMachineSensorData, load_ratio: float,
                     best_name: str, best: Dict, base_energy: float, base_water: float) -> str:
        reasons = []
        if best_name == "use_load_size_setting":
            reasons.append(
                f"Load is only {load_ratio*100:.0f}% of machine capacity, but the machine would otherwise fill "
                f"water for a near-full load; matching water level to actual load size avoids waste."
            )
        elif best_name == "lower_wash_temperature":
            reasons.append(
                f"Soil level is '{data.soil_level}', which does not require water heated to "
                f"{data.water_temp_c:.0f}C; a cooler wash cleans adequately while avoiding heating-element energy."
            )
        elif best_name == "shorten_cycle":
            reasons.append(
                f"Soil level is 'low', so a shorter cycle ({best['params']['cycle_minutes']:.0f} min vs "
                f"{data.selected_cycle_minutes:.0f} min) still cleans effectively while using less energy and water."
            )
        else:
            reasons.append("Current load size, temperature and cycle length are already close to optimal.")
 
        e_pct = 0 if base_energy == 0 else round(100 * (base_energy - best["energy"]) / base_energy, 1)
        w_pct = 0 if base_water == 0 else round(100 * (base_water - best["water"]) / base_water, 1)
        reasons.append(f"Estimated energy change: {e_pct}%, water change: {w_pct}% vs baseline (simulated).")
        return " ".join(reasons)
 
    # ------------------------------------------------------------------
    # Desert Air Cooler
    # ------------------------------------------------------------------
 
    def optimize_air_cooler(self, data: AirCoolerSensorData) -> OptimizationResult:
        c = self.constraints
        warnings: List[str] = []
 
        # Baseline reflects the appliance's CURRENT configured behavior (is it
        # actively trying to run evaporative cooling right now, based on pad
        # wetness), not an already-safe assumption. This is deliberate: if the
        # tank is critically low but the pad is still reported wet, the
        # baseline should show the (unsafe/wasteful) current behavior so the
        # optimizer's low-water rule has something real to fix.
        base_evap_active = data.pad_wetness_percent > 0
        base_energy = air_cooler_energy_kwh(data.fan_speed, data.rated_power_w, data.runtime_hours_today)
        base_water = air_cooler_water_liters(
            data.pad_wetness_percent, data.runtime_hours_today, data.humidity_percent,
            evaporative_active=base_evap_active,
        )
        base_cost = compute_cost_inr(base_energy, base_water)
        base_carbon = compute_carbon_kg(base_energy)
 
        candidates: Dict[str, Dict[str, float]] = {
            "no_change": dict(
                fan_speed=data.fan_speed, pad_wetness=data.pad_wetness_percent,
                evap_active=base_evap_active,
            ),
        }
 
        # 1. Low tank level -> must not run evaporative cooling (safety/performance: avoid dry-pump run)
        if data.water_tank_level_percent < c.cooler_min_tank_percent:
            candidates["switch_to_fan_only_low_water"] = dict(
                fan_speed=data.fan_speed, pad_wetness=0.0, evap_active=False,
            )
            warnings.append("Water tank level is below the safe minimum; evaporative cooling disabled to protect the pump.")
 
        # 2. High humidity -> evaporative cooling is ineffective, wastes water for little cooling benefit
        if data.humidity_percent >= 60 and base_evap_active:
            candidates["switch_to_fan_only_high_humidity"] = dict(
                fan_speed=data.fan_speed, pad_wetness=0.0, evap_active=False,
            )
 
        # 3. Fan speed higher than needed given the outdoor-indoor temperature gap
        temp_gap = data.outdoor_temp_c - data.room_temp_c
        if data.fan_speed >= 4 and temp_gap < 5:
            candidates["reduce_fan_speed"] = dict(
                fan_speed=max(2, data.fan_speed - 2), pad_wetness=data.pad_wetness_percent,
                evap_active=base_evap_active,
            )
 
        scored = {}
        details = {}
        for name, params in candidates.items():
            if params["evap_active"] and data.water_tank_level_percent < c.cooler_min_tank_percent:
                continue  # safety: cannot run evaporative mode on near-empty tank
            energy = air_cooler_energy_kwh(params["fan_speed"], data.rated_power_w, data.runtime_hours_today)
            water = air_cooler_water_liters(
                params["pad_wetness"], data.runtime_hours_today, data.humidity_percent,
                evaporative_active=params["evap_active"],
            )
            cost = compute_cost_inr(energy, water)
            carbon = compute_carbon_kg(energy)
            score = _weighted_score(energy, water, cost, carbon,
                                     base_energy, base_water or 1e-9, base_cost, base_carbon,
                                     self.weights)
            scored[name] = score
            details[name] = dict(energy=energy, water=water, cost=cost, carbon=carbon, params=params)
 
        best_name = min(scored, key=scored.get)
        best = details[best_name]
 
        explanation = self._explain_cooler(data, temp_gap, best_name, best, base_energy, base_water)
 
        return OptimizationResult(
            appliance=ApplianceType.AIR_COOLER.value,
            recommended_action=self._cooler_action_label(best_name, best["params"]),
            baseline_energy_kwh=base_energy,
            optimized_energy_kwh=best["energy"],
            baseline_water_liters=base_water,
            optimized_water_liters=best["water"],
            estimated_cost_saving_inr=round(base_cost - best["cost"], 2),
            estimated_carbon_reduction_kg=round(base_carbon - best["carbon"], 3),
            explanation=explanation,
            candidate_scores=scored,
            warnings=warnings,
        )
 
    def _cooler_action_label(self, name: str, params: Dict) -> str:
        labels = {
            "no_change": "Keep current cooler settings",
            "switch_to_fan_only_low_water": "Switch to fan-only mode (water tank low)",
            "switch_to_fan_only_high_humidity": "Switch to fan-only mode (humidity too high for evaporative cooling)",
            "reduce_fan_speed": f"Reduce fan speed to level {params['fan_speed']}",
        }
        return labels.get(name, name)
 
    def _explain_cooler(self, data: AirCoolerSensorData, temp_gap: float,
                         best_name: str, best: Dict, base_energy: float, base_water: float) -> str:
        reasons = []
        if best_name == "switch_to_fan_only_low_water":
            reasons.append(
                f"Water tank is at {data.water_tank_level_percent:.0f}%, below the safe minimum; running the pump "
                f"dry risks damage, so evaporative cooling is disabled and fan-only mode is used instead."
            )
        elif best_name == "switch_to_fan_only_high_humidity":
            reasons.append(
                f"Humidity is {data.humidity_percent:.0f}%, which sharply reduces evaporative cooling effectiveness; "
                f"continuing to wet the pad wastes water for little comfort benefit, so fan-only mode is recommended."
            )
        elif best_name == "reduce_fan_speed":
            reasons.append(
                f"Outdoor-indoor temperature gap is only {temp_gap:.1f}C, so a high fan speed "
                f"({data.fan_speed}) is not needed; a lower speed still maintains comfort with less energy draw."
            )
        else:
            reasons.append("Current fan speed and pad wetness are already appropriate for the humidity and temperature conditions.")
 
        e_pct = 0 if base_energy == 0 else round(100 * (base_energy - best["energy"]) / base_energy, 1)
        w_pct = 0 if base_water == 0 else round(100 * (base_water - best["water"]) / base_water, 1)
        reasons.append(f"Estimated energy change: {e_pct}%, water change: {w_pct}% vs baseline (simulated).")
        return " ".join(reasons)