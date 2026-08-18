"""
test_cooler_optimizer.py
--------------------------
Unit tests for cooler_optimizer.py.
 
Run with:  python -m unittest test_cooler_optimizer.py -v
"""
 
import unittest
 
from cooler_optimizer import (
    optimize_cooler,
    estimate_energy,
    estimate_water_liters_per_hour,
    estimate_comfort_score,
    FAN_SPEEDS,
    PUMP_DUTIES,
)
 
 
class TestEstimateEnergy(unittest.TestCase):
    def test_energy_at_current_setting_matches_current_power(self):
        e = estimate_energy(fan_speed=3, pump_duty=50, current_fan_speed=3,
                             current_pump_duty=50, current_power=150)
        self.assertEqual(e, 150.0)
 
    def test_higher_fan_speed_uses_more_energy(self):
        low = estimate_energy(fan_speed=1, pump_duty=0, current_fan_speed=3,
                               current_pump_duty=0, current_power=100)
        high = estimate_energy(fan_speed=5, pump_duty=0, current_fan_speed=3,
                                current_pump_duty=0, current_power=100)
        self.assertGreater(high, low)
 
    def test_higher_pump_duty_uses_more_energy(self):
        low = estimate_energy(fan_speed=3, pump_duty=0, current_fan_speed=3,
                               current_pump_duty=50, current_power=100)
        high = estimate_energy(fan_speed=3, pump_duty=100, current_fan_speed=3,
                                current_pump_duty=50, current_power=100)
        self.assertGreater(high, low)
 
    def test_deterministic(self):
        args = dict(fan_speed=4, pump_duty=75, current_fan_speed=3,
                    current_pump_duty=50, current_power=120)
        self.assertEqual(estimate_energy(**args), estimate_energy(**args))
 
 
class TestEstimateWater(unittest.TestCase):
    def test_zero_pump_duty_uses_no_water(self):
        self.assertEqual(estimate_water_liters_per_hour(pump_duty=0, humidity=50), 0.0)
 
    def test_higher_pump_duty_uses_more_water(self):
        low = estimate_water_liters_per_hour(pump_duty=25, humidity=50)
        high = estimate_water_liters_per_hour(pump_duty=100, humidity=50)
        self.assertGreater(high, low)
 
    def test_higher_humidity_increases_water_rate_at_fixed_duty(self):
        """Even though evaporative cooling is less effective at high humidity,
        the pump still physically draws more water at a fixed duty cycle when
        the humidity multiplier is higher -- this is exactly the waste the
        optimizer should avoid by lowering pump_duty, not the water model
        pretending humidity reduces water draw."""
        dry = estimate_water_liters_per_hour(pump_duty=100, humidity=30)
        humid = estimate_water_liters_per_hour(pump_duty=100, humidity=90)
        self.assertGreater(humid, dry)
 
 
class TestEstimateComfortScore(unittest.TestCase):
    def test_unoccupied_always_scores_100(self):
        for fs in FAN_SPEEDS:
            for pd in PUMP_DUTIES:
                self.assertEqual(
                    estimate_comfort_score(fs, pd, temperature=35, humidity=80, occupancy=False),
                    100.0,
                )
 
    def test_higher_fan_speed_increases_comfort(self):
        low = estimate_comfort_score(fan_speed=1, pump_duty=0, temperature=32, humidity=40, occupancy=True)
        high = estimate_comfort_score(fan_speed=5, pump_duty=0, temperature=32, humidity=40, occupancy=True)
        self.assertGreater(high, low)
 
    def test_pump_duty_helps_less_at_high_humidity(self):
        """Core humidity-aware behavior: the SAME pump_duty buys less comfort
        improvement when humidity is high vs. low."""
        dry_gain = (
            estimate_comfort_score(3, 100, temperature=32, humidity=30, occupancy=True)
            - estimate_comfort_score(3, 0, temperature=32, humidity=30, occupancy=True)
        )
        humid_gain = (
            estimate_comfort_score(3, 100, temperature=32, humidity=90, occupancy=True)
            - estimate_comfort_score(3, 0, temperature=32, humidity=90, occupancy=True)
        )
        self.assertGreater(dry_gain, humid_gain)
 
    def test_hotter_room_reduces_comfort_score(self):
        cool_room = estimate_comfort_score(3, 50, temperature=29, humidity=40, occupancy=True)
        hot_room = estimate_comfort_score(3, 50, temperature=40, humidity=40, occupancy=True)
        self.assertGreater(cool_room, hot_room)
 
    def test_score_bounded_0_to_100(self):
        score = estimate_comfort_score(5, 100, temperature=25, humidity=10, occupancy=True)
        self.assertLessEqual(score, 100.0)
        low_score = estimate_comfort_score(1, 0, temperature=45, humidity=90, occupancy=True)
        self.assertGreaterEqual(low_score, 0.0)
 
 
class TestOptimizeCooler(unittest.TestCase):
    def test_returns_all_required_keys(self):
        result = optimize_cooler(
            temperature=33, humidity=45, occupancy=True,
            water_level=70, fan_speed=3, pump_duty=50, power=150,
        )
        expected_keys = {
            "recommended_fan_speed", "recommended_pump_duty",
            "estimated_water_saving", "estimated_energy_saving", "reason", "details",
        }
        self.assertEqual(set(result.keys()), expected_keys)
 
    def test_recommended_settings_are_valid(self):
        result = optimize_cooler(
            temperature=34, humidity=50, occupancy=True,
            water_level=80, fan_speed=4, pump_duty=75, power=180,
        )
        self.assertIn(result["recommended_fan_speed"], FAN_SPEEDS)
        self.assertIn(result["recommended_pump_duty"], PUMP_DUTIES)
 
    def test_deterministic_same_inputs_same_output(self):
        kwargs = dict(
            temperature=35, humidity=60, occupancy=True,
            water_level=60, fan_speed=3, pump_duty=50, power=160,
        )
        r1 = optimize_cooler(**kwargs)
        r2 = optimize_cooler(**kwargs)
        self.assertEqual(r1, r2)
 
    # --- Safety logic: the core required behavior ---
 
    def test_low_water_level_forces_pump_off(self):
        result = optimize_cooler(
            temperature=34, humidity=40, occupancy=True,
            water_level=10, fan_speed=3, pump_duty=75, power=150,
        )
        self.assertEqual(result["recommended_pump_duty"], 0)
        self.assertIn("safe minimum", result["reason"].lower())
 
    def test_low_water_level_never_offers_nonzero_pump_candidate(self):
        result = optimize_cooler(
            temperature=34, humidity=40, occupancy=True,
            water_level=5, fan_speed=3, pump_duty=100, power=150,
        )
        for e in result["details"]["evaluations"]:
            self.assertEqual(e["pump_duty"], 0)
 
    def test_water_level_exactly_at_minimum_is_not_forced_off(self):
        """Boundary check: water_level == min_water_level_percent should NOT
        trigger the safety cutoff (only strictly below the minimum)."""
        result = optimize_cooler(
            temperature=34, humidity=40, occupancy=True,
            water_level=15, fan_speed=3, pump_duty=50, power=150,
            min_water_level_percent=15,
        )
        self.assertFalse(result["details"]["pump_forced_off"])
 
    def test_water_saving_is_zero_or_positive_when_pump_forced_off(self):
        result = optimize_cooler(
            temperature=34, humidity=40, occupancy=True,
            water_level=8, fan_speed=3, pump_duty=80, power=150,
        )
        self.assertGreaterEqual(result["estimated_water_saving"], 0)
 
    # --- Humidity-aware behavior ---
 
    def test_high_humidity_reduces_recommended_pump_duty(self):
        dry_result = optimize_cooler(
            temperature=33, humidity=25, occupancy=True,
            water_level=80, fan_speed=3, pump_duty=75, power=150,
        )
        humid_result = optimize_cooler(
            temperature=33, humidity=90, occupancy=True,
            water_level=80, fan_speed=3, pump_duty=75, power=150,
        )
        self.assertLessEqual(humid_result["recommended_pump_duty"], dry_result["recommended_pump_duty"])
 
    # --- General optimization behavior ---
 
    def test_unoccupied_room_recommends_minimal_resource_use(self):
        result = optimize_cooler(
            temperature=33, humidity=50, occupancy=False,
            water_level=80, fan_speed=4, pump_duty=75, power=150,
        )
        self.assertEqual(result["recommended_pump_duty"], 0)
        self.assertEqual(result["recommended_fan_speed"], min(FAN_SPEEDS))
 
    def test_impossible_comfort_threshold_falls_back_gracefully(self):
        result = optimize_cooler(
            temperature=40, humidity=95, occupancy=True,
            water_level=80, fan_speed=3, pump_duty=50, power=150,
            min_comfort_threshold=999,
        )
        self.assertIn("no available setting", result["reason"].lower())
        self.assertIn(result["recommended_fan_speed"], FAN_SPEEDS)
 
    def test_savings_non_negative_for_a_wasteful_baseline(self):
        """Cooler currently running at max fan + max pump in mild, dry
        conditions -- optimizer should find a lower-resource setting that's
        still comfortable, i.e. non-negative savings."""
        result = optimize_cooler(
            temperature=30, humidity=30, occupancy=True,
            water_level=80, fan_speed=5, pump_duty=100, power=200,
        )
        self.assertGreaterEqual(result["estimated_energy_saving"], 0)
        self.assertGreaterEqual(result["estimated_water_saving"], 0)
 
    def test_details_include_full_grid_when_pump_available(self):
        result = optimize_cooler(
            temperature=33, humidity=50, occupancy=True,
            water_level=80, fan_speed=3, pump_duty=50, power=150,
        )
        combos = {(e["fan_speed"], e["pump_duty"]) for e in result["details"]["evaluations"]}
        self.assertEqual(combos, {(fs, pd) for fs in FAN_SPEEDS for pd in PUMP_DUTIES})
 
    def test_custom_grid_is_respected(self):
        result = optimize_cooler(
            temperature=33, humidity=50, occupancy=True,
            water_level=80, fan_speed=3, pump_duty=50, power=150,
            fan_speeds=(2, 4), pump_duties=(0, 50),
        )
        self.assertIn(result["recommended_fan_speed"], (2, 4))
        self.assertIn(result["recommended_pump_duty"], (0, 50))
 
 
if __name__ == "__main__":
    unittest.main(verbosity=2)
 