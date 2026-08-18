"""
test_wm_optimizer.py
---------------------
Unit tests for wm_optimizer.py.
 
Run with:  python -m unittest test_wm_optimizer.py -v
"""
 
import unittest
from datetime import datetime
 
from wm_optimizer import (
    optimize_washing_machine,
    estimate_duration_minutes,
    estimate_energy,
    estimate_water,
    estimate_performance,
    MODES,
)
 
FIXED_NOW = datetime(2026, 8, 15, 9, 0, 0)
 
 
class TestEstimateDuration(unittest.TestCase):
    def test_reference_load_uses_base_duration(self):
        self.assertEqual(estimate_duration_minutes("Normal", 5.0), 60)
        self.assertEqual(estimate_duration_minutes("Eco", 5.0), 90)
        self.assertEqual(estimate_duration_minutes("Quick", 5.0), 30)
 
    def test_larger_load_increases_duration(self):
        base = estimate_duration_minutes("Normal", 5.0)
        bigger = estimate_duration_minutes("Normal", 8.0)
        self.assertGreater(bigger, base)
 
    def test_duration_never_decreases_below_reference(self):
        small_load = estimate_duration_minutes("Quick", 2.0)
        self.assertEqual(small_load, 30)  # no discount below reference load
 
 
class TestEstimateEnergyAndWater(unittest.TestCase):
    def test_energy_at_current_cycle_matches_current_energy(self):
        e = estimate_energy("Normal", current_cycle="Normal", current_energy=1.5)
        self.assertEqual(e, 1.5)
 
    def test_water_at_current_cycle_matches_current_water(self):
        w = estimate_water("Normal", current_cycle="Normal", current_water=60.0)
        self.assertEqual(w, 60.0)
 
    def test_eco_and_quick_use_less_than_normal(self):
        normal_e = estimate_energy("Normal", "Normal", 1.5)
        eco_e = estimate_energy("Eco", "Normal", 1.5)
        quick_e = estimate_energy("Quick", "Normal", 1.5)
        self.assertLess(eco_e, normal_e)
        self.assertLess(quick_e, eco_e)
 
        normal_w = estimate_water("Normal", "Normal", 60.0)
        eco_w = estimate_water("Eco", "Normal", 60.0)
        quick_w = estimate_water("Quick", "Normal", 60.0)
        self.assertLess(eco_w, normal_w)
        self.assertLess(quick_w, eco_w)
 
    def test_calibration_is_symmetric_regardless_of_reference_cycle(self):
        """If the user's current cycle is already Eco, ratios still work out
        so that estimate_energy(Eco, Eco, X) == X."""
        e = estimate_energy("Eco", current_cycle="Eco", current_energy=0.8)
        self.assertEqual(e, 0.8)
 
 
class TestEstimatePerformance(unittest.TestCase):
    def test_higher_dirt_reduces_performance(self):
        low = estimate_performance("Normal", "low", load_kg=5, water_hardness=100)
        high = estimate_performance("Normal", "high", load_kg=5, water_hardness=100)
        self.assertGreater(low, high)
 
    def test_quick_mode_suffers_most_from_dirt(self):
        normal_drop = (
            estimate_performance("Normal", "low", 5, 100)
            - estimate_performance("Normal", "high", 5, 100)
        )
        quick_drop = (
            estimate_performance("Quick", "low", 5, 100)
            - estimate_performance("Quick", "high", 5, 100)
        )
        self.assertGreater(quick_drop, normal_drop)
 
    def test_high_hardness_reduces_performance(self):
        soft = estimate_performance("Eco", "medium", 5, water_hardness=80)
        hard = estimate_performance("Eco", "medium", 5, water_hardness=300)
        self.assertGreater(soft, hard)
 
    def test_overload_penalizes_quick_mode(self):
        normal_load = estimate_performance("Quick", "medium", load_kg=5, water_hardness=100)
        big_load = estimate_performance("Quick", "medium", load_kg=8, water_hardness=100)
        self.assertGreater(normal_load, big_load)
 
    def test_score_bounded_0_to_100(self):
        score = estimate_performance("Quick", "high", load_kg=9, water_hardness=500)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
 
 
class TestOptimizeWashingMachine(unittest.TestCase):
    def test_returns_all_required_keys(self):
        result = optimize_washing_machine(
            load_kg=5, dirt_level="medium", water_hardness=100,
            current_cycle="Normal", current_water=60, current_energy=1.5,
            deadline_minutes=120, electricity_cost=8.0, now=FIXED_NOW,
        )
        expected_keys = {
            "recommended_mode", "recommended_start_time", "water_saving",
            "energy_saving", "cost_saving", "reason", "details",
        }
        self.assertEqual(set(result.keys()), expected_keys)
 
    def test_recommended_mode_is_valid(self):
        result = optimize_washing_machine(
            load_kg=5, dirt_level="low", water_hardness=90,
            current_cycle="Normal", current_water=60, current_energy=1.5,
            deadline_minutes=100, electricity_cost=8.0, now=FIXED_NOW,
        )
        self.assertIn(result["recommended_mode"], MODES)
 
    def test_deterministic_same_inputs_same_output(self):
        kwargs = dict(
            load_kg=6, dirt_level="high", water_hardness=200,
            current_cycle="Normal", current_water=65, current_energy=1.6,
            deadline_minutes=100, electricity_cost=8.0, now=FIXED_NOW,
        )
        r1 = optimize_washing_machine(**kwargs)
        r2 = optimize_washing_machine(**kwargs)
        self.assertEqual(r1, r2)
 
    def test_low_dirt_ample_deadline_picks_eco_or_quick_over_normal(self):
        """Lightly soiled load with plenty of time should not need the most
        resource-intensive Normal mode."""
        result = optimize_washing_machine(
            load_kg=4, dirt_level="low", water_hardness=80,
            current_cycle="Normal", current_water=55, current_energy=1.4,
            deadline_minutes=180, electricity_cost=8.0, now=FIXED_NOW,
        )
        self.assertIn(result["recommended_mode"], ("Eco", "Quick"))
        self.assertGreaterEqual(result["water_saving"], 0)
        self.assertGreaterEqual(result["energy_saving"], 0)
 
    def test_high_dirt_tight_deadline_relaxes_performance_and_explains(self):
        """Heavily soiled load with only 35 minutes available: Quick is the
        only mode that fits the deadline at all, even though it can't hit a
        high performance bar on heavy dirt -- optimizer must still return a
        usable recommendation and explain the trade-off."""
        result = optimize_washing_machine(
            load_kg=5, dirt_level="high", water_hardness=250,
            current_cycle="Normal", current_water=60, current_energy=1.5,
            deadline_minutes=35, electricity_cost=8.0, now=FIXED_NOW,
        )
        self.assertEqual(result["recommended_mode"], "Quick")
        self.assertIn("deadline", result["reason"].lower())
 
    def test_impossible_deadline_falls_back_to_fastest_mode(self):
        result = optimize_washing_machine(
            load_kg=5, dirt_level="medium", water_hardness=100,
            current_cycle="Normal", current_water=60, current_energy=1.5,
            deadline_minutes=10, electricity_cost=8.0, now=FIXED_NOW,
        )
        self.assertEqual(result["recommended_mode"], "Quick")
        self.assertIn("no mode can finish", result["reason"].lower())
 
    def test_recommended_start_time_leaves_room_to_finish_by_deadline(self):
        result = optimize_washing_machine(
            load_kg=5, dirt_level="medium", water_hardness=100,
            current_cycle="Normal", current_water=60, current_energy=1.5,
            deadline_minutes=120, electricity_cost=8.0, now=FIXED_NOW,
        )
        start = datetime.fromisoformat(result["recommended_start_time"])
        self.assertGreaterEqual(start, FIXED_NOW)
 
    def test_start_time_never_before_now(self):
        """Even if the chosen mode's duration is much shorter than the
        deadline, recommended_start_time should never be earlier than now."""
        result = optimize_washing_machine(
            load_kg=3, dirt_level="low", water_hardness=60,
            current_cycle="Normal", current_water=50, current_energy=1.2,
            deadline_minutes=500, electricity_cost=8.0, now=FIXED_NOW,
        )
        start = datetime.fromisoformat(result["recommended_start_time"])
        self.assertGreaterEqual(start, FIXED_NOW)
 
    def test_cost_saving_consistent_with_energy_and_water_savings(self):
        result = optimize_washing_machine(
            load_kg=5, dirt_level="low", water_hardness=90,
            current_cycle="Normal", current_water=60, current_energy=1.5,
            deadline_minutes=150, electricity_cost=8.0, water_cost_per_liter=0.05,
            now=FIXED_NOW,
        )
        expected_cost_saving = round(
            result["energy_saving"] * 8.0 + result["water_saving"] * 0.05, 2
        )
        self.assertEqual(result["cost_saving"], expected_cost_saving)
 
    def test_case_insensitive_current_cycle(self):
        result = optimize_washing_machine(
            load_kg=5, dirt_level="medium", water_hardness=100,
            current_cycle="normal", current_water=60, current_energy=1.5,
            deadline_minutes=120, electricity_cost=8.0, now=FIXED_NOW,
        )
        self.assertIn(result["recommended_mode"], MODES)
 
    def test_details_breakdown_includes_all_three_modes(self):
        result = optimize_washing_machine(
            load_kg=5, dirt_level="medium", water_hardness=100,
            current_cycle="Normal", current_water=60, current_energy=1.5,
            deadline_minutes=120, electricity_cost=8.0, now=FIXED_NOW,
        )
        evaluated_modes = {e["mode"] for e in result["details"]["evaluations"]}
        self.assertEqual(evaluated_modes, set(MODES))
 
 
if __name__ == "__main__":
    unittest.main(verbosity=2)
 