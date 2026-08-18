"""
test_household_optimizer.py
------------------------------
Test dataset + unit tests for household_optimizer.py.
 
Run with:  python -m unittest test_household_optimizer.py -v
"""
 
import copy
import unittest
 
from household_optimizer import optimize_household, _compute_resource_score, _safe_ratio
 
 
# ---------------------------------------------------------------------------
# Test dataset: a realistic (simulated) household state snapshot
# ---------------------------------------------------------------------------
 
def sample_household_state():
    """Returns a fresh, deterministic sample household state dict each call
    (fresh dict so tests can mutate it without affecting each other)."""
    return {
        "ac": {
            "temperature": 25,
            "humidity": 55,
            "occupancy": True,
            "current_setpoint": 20,
            "current_power": 1600,
            "outside_temperature": 39,
        },
        "refrigerator": {
            "internal_temperature": 2.0,
            "target_temperature": 2.0,
            "ambient_temperature": 30,
            "door_open_count": 6,
            "rated_power_w": 150.0,
            "frost_thickness_mm": 1.0,
        },
        "washing_machine": {
            "load_kg": 5,
            "dirt_level": "medium",
            "water_hardness": 120,
            "current_cycle": "Normal",
            "current_water": 60,
            "current_energy": 1.5,
            "deadline_minutes": 120,
            "electricity_cost": 8.0,
        },
        "cooler": {
            "temperature": 33,
            "humidity": 45,
            "occupancy": True,
            "water_level": 70,
            "fan_speed": 5,
            "pump_duty": 100,
            "power": 200,
        },
    }
 
 
class TestHouseholdOptimizerStructure(unittest.TestCase):
    def setUp(self):
        self.state = sample_household_state()
 
    def test_returns_all_required_top_level_keys(self):
        result = optimize_household(**self.state)
        expected_keys = {"energy", "water", "cost", "carbon", "resource_score", "recommendations"}
        self.assertEqual(set(result.keys()), expected_keys)
 
    def test_energy_water_cost_carbon_sub_keys(self):
        result = optimize_household(**self.state)
        for key in ("energy", "water"):
            self.assertEqual(
                set(result[key].keys()),
                {f"baseline_{'kwh' if key=='energy' else 'liters'}",
                 f"optimized_{'kwh' if key=='energy' else 'liters'}",
                 f"saving_{'kwh' if key=='energy' else 'liters'}"},
            )
        for key in ("cost", "carbon"):
            unit = "inr" if key == "cost" else "kg"
            self.assertEqual(
                set(result[key].keys()),
                {f"baseline_{unit}", f"optimized_{unit}", f"saving_{unit}"},
            )
 
    def test_recommendations_cover_all_four_appliances(self):
        result = optimize_household(**self.state)
        self.assertEqual(len(result["recommendations"]), 4)
        appliances = {r["appliance"] for r in result["recommendations"]}
        self.assertEqual(appliances, {"ac", "refrigerator", "washing_machine", "cooler"})
 
    def test_each_recommendation_has_required_fields(self):
        result = optimize_household(**self.state)
        expected_fields = {
            "appliance", "recommendation", "baseline_energy_kwh", "optimized_energy_kwh",
            "baseline_water_liters", "optimized_water_liters", "reason",
        }
        for r in result["recommendations"]:
            self.assertEqual(set(r.keys()), expected_fields)
            self.assertTrue(len(r["reason"]) > 0)
 
 
class TestHouseholdOptimizerAggregation(unittest.TestCase):
    def setUp(self):
        self.state = sample_household_state()
 
    def test_deterministic_same_inputs_same_output(self):
        r1 = optimize_household(**copy.deepcopy(self.state))
        r2 = optimize_household(**copy.deepcopy(self.state))
        self.assertEqual(r1, r2)
 
    def test_total_energy_equals_sum_of_per_appliance_energy(self):
        result = optimize_household(**self.state)
        total_baseline = sum(r["baseline_energy_kwh"] for r in result["recommendations"])
        total_optimized = sum(r["optimized_energy_kwh"] for r in result["recommendations"])
        self.assertAlmostEqual(result["energy"]["baseline_kwh"], total_baseline, places=3)
        self.assertAlmostEqual(result["energy"]["optimized_kwh"], total_optimized, places=3)
 
    def test_total_water_equals_sum_of_per_appliance_water(self):
        result = optimize_household(**self.state)
        total_baseline = sum(r["baseline_water_liters"] for r in result["recommendations"])
        total_optimized = sum(r["optimized_water_liters"] for r in result["recommendations"])
        self.assertAlmostEqual(result["water"]["baseline_liters"], total_baseline, places=3)
        self.assertAlmostEqual(result["water"]["optimized_liters"], total_optimized, places=3)
 
    def test_energy_saving_equals_baseline_minus_optimized(self):
        result = optimize_household(**self.state)
        expected = round(result["energy"]["baseline_kwh"] - result["energy"]["optimized_kwh"], 4)
        self.assertEqual(result["energy"]["saving_kwh"], expected)
 
    def test_cost_derived_from_energy_and_water_using_shared_constants(self):
        from calculations import compute_cost_inr
        result = optimize_household(**self.state)
        expected_baseline_cost = compute_cost_inr(
            result["energy"]["baseline_kwh"], result["water"]["baseline_liters"]
        )
        self.assertEqual(result["cost"]["baseline_inr"], expected_baseline_cost)
 
    def test_carbon_derived_from_energy_using_shared_constant(self):
        from calculations import compute_carbon_kg
        result = optimize_household(**self.state)
        expected_baseline_carbon = compute_carbon_kg(result["energy"]["baseline_kwh"])
        self.assertEqual(result["carbon"]["baseline_kg"], expected_baseline_carbon)
 
    def test_optimized_never_exceeds_baseline_for_a_wasteful_household(self):
        """This sample state is deliberately wasteful (cold AC setpoint, max
        cooler settings) -- optimization should never recommend using MORE
        of any resource than the baseline in this scenario."""
        result = optimize_household(**self.state)
        self.assertLessEqual(result["energy"]["optimized_kwh"], result["energy"]["baseline_kwh"])
        self.assertLessEqual(result["water"]["optimized_liters"], result["water"]["baseline_liters"])
        self.assertLessEqual(result["cost"]["optimized_inr"], result["cost"]["baseline_inr"])
        self.assertLessEqual(result["carbon"]["optimized_kg"], result["carbon"]["baseline_kg"])
 
 
class TestResourceScore(unittest.TestCase):
    def test_score_bounded_0_to_100(self):
        state = sample_household_state()
        result = optimize_household(**state)
        self.assertGreaterEqual(result["resource_score"], 0.0)
        self.assertLessEqual(result["resource_score"], 100.0)
 
    def test_perfectly_optimal_household_scores_100(self):
        score = _compute_resource_score(
            baseline_energy=10, optimized_energy=10,
            baseline_water=50, optimized_water=50,
            baseline_cost=100, optimized_cost=100,
            baseline_carbon=8, optimized_carbon=8,
        )
        self.assertEqual(score, 100.0)
 
    def test_wasteful_household_scores_lower_than_efficient_one(self):
        efficient_state = sample_household_state()
        efficient_state["ac"]["current_setpoint"] = 26  # already at the efficient/comfort-safe ceiling
        efficient_state["cooler"]["pump_duty"] = 0
        efficient_state["cooler"]["fan_speed"] = 2
 
        wasteful_state = sample_household_state()  # cold AC + maxed-out cooler (deliberately wasteful)
 
        efficient_result = optimize_household(**efficient_state)
        wasteful_result = optimize_household(**wasteful_state)
        self.assertGreaterEqual(efficient_result["resource_score"], wasteful_result["resource_score"])
 
    def test_safe_ratio_handles_zero_baseline(self):
        self.assertEqual(_safe_ratio(optimized=0.0, baseline=0.0), 1.0)
 
    def test_safe_ratio_clamped_between_0_and_1(self):
        self.assertEqual(_safe_ratio(optimized=150, baseline=100), 1.0)  # optimized > baseline, clamp up
        self.assertEqual(_safe_ratio(optimized=-10, baseline=100), 0.0)  # negative, clamp down
 
 
class TestHouseholdOptimizerAppliancesIndividually(unittest.TestCase):
    def setUp(self):
        self.state = sample_household_state()
 
    def test_ac_recommendation_present_and_valid(self):
        result = optimize_household(**self.state)
        ac_rec = next(r for r in result["recommendations"] if r["appliance"] == "ac")
        self.assertIn("Set AC to", ac_rec["recommendation"])
        self.assertGreater(ac_rec["baseline_energy_kwh"], 0)
 
    def test_refrigerator_recommendation_present_and_safe(self):
        result = optimize_household(**self.state)
        fridge_rec = next(r for r in result["recommendations"] if r["appliance"] == "refrigerator")
        self.assertGreater(fridge_rec["baseline_energy_kwh"], 0)
        self.assertIn(fridge_rec["recommendation"], (
            "Keep setpoint at 2.0C", "Raise setpoint to 3.0C",
        ))
 
    def test_refrigerator_never_recommends_outside_safe_band(self):
        state = sample_household_state()
        state["refrigerator"]["target_temperature"] = 0.0  # below safe minimum
        result = optimize_household(**state)
        fridge_rec = next(r for r in result["recommendations"] if r["appliance"] == "refrigerator")
        self.assertNotIn("0.0C", fridge_rec["recommendation"])
 
    def test_washing_machine_recommendation_present(self):
        result = optimize_household(**self.state)
        wm_rec = next(r for r in result["recommendations"] if r["appliance"] == "washing_machine")
        self.assertIn("mode", wm_rec["recommendation"].lower())
        self.assertGreater(wm_rec["baseline_water_liters"], 0)
 
    def test_cooler_recommendation_reflects_low_water_safety_rule(self):
        state = sample_household_state()
        state["cooler"]["water_level"] = 5  # below the safety floor
        result = optimize_household(**state)
        cooler_rec = next(r for r in result["recommendations"] if r["appliance"] == "cooler")
        self.assertIn("pump duty 0%", cooler_rec["recommendation"])
        self.assertEqual(cooler_rec["optimized_water_liters"], 0.0)
 
 
class TestHouseholdOptimizerBasedOnlyOnProvidedData(unittest.TestCase):
    def test_two_different_states_never_collide_to_same_result(self):
        state_a = sample_household_state()
        state_b = sample_household_state()
        state_b["ac"]["current_power"] = 2500  # meaningfully different input
 
        result_a = optimize_household(**state_a)
        result_b = optimize_household(**state_b)
        self.assertNotEqual(result_a["energy"]["baseline_kwh"], result_b["energy"]["baseline_kwh"])
 
    def test_optional_fields_have_safe_defaults(self):
        """electricity_cost/water_cost_per_liter/thresholds are optional in
        the washing_machine/cooler/ac states; omitting them should not
        raise, and should fall back to the shared calculations.py constants."""
        state = sample_household_state()
        del state["washing_machine"]["electricity_cost"]
        result = optimize_household(**state)  # should not raise
        self.assertIn("recommendations", result)
 
 
if __name__ == "__main__":
    unittest.main(verbosity=2)
 