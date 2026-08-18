"""
test_ac_optimizer.py
---------------------
Unit tests for ac_optimizer.py.
 
Run with:  python -m unittest test_ac_optimizer.py -v
"""
 
import unittest
 
from ac_optimizer import (
    optimize_ac,
    estimate_energy,
    comfort_score,
    CANDIDATE_SETPOINTS,
)
 
 
class TestEstimateEnergy(unittest.TestCase):
    def test_energy_at_current_setpoint_matches_current_power(self):
        """estimate_energy at the current setpoint must reproduce current_power
        exactly (self-consistent calibration)."""
        e = estimate_energy(
            setpoint=24, outside_temperature=35, humidity=50,
            current_setpoint=24, current_power=1200,
        )
        self.assertEqual(e, 1200.0)
 
    def test_higher_setpoint_uses_less_energy_when_hot_outside(self):
        low = estimate_energy(setpoint=22, outside_temperature=38, humidity=50,
                               current_setpoint=24, current_power=1200)
        high = estimate_energy(setpoint=26, outside_temperature=38, humidity=50,
                                current_setpoint=24, current_power=1200)
        self.assertLess(high, low)
 
    def test_higher_humidity_increases_energy_relative_to_baseline(self):
        """Humidity affects the load-factor ratio between a candidate setpoint
        and the reference setpoint. Using setpoint != current_setpoint (so the
        ratio isn't trivially 1.0 regardless of humidity), higher humidity
        should push the candidate's estimated energy higher relative to the
        fixed baseline current_power."""
        low_humidity = estimate_energy(setpoint=26, outside_temperature=36, humidity=40,
                                        current_setpoint=22, current_power=1000)
        high_humidity = estimate_energy(setpoint=26, outside_temperature=36, humidity=80,
                                         current_setpoint=22, current_power=1000)
        self.assertGreater(high_humidity, low_humidity)
 
    def test_energy_is_deterministic(self):
        args = dict(setpoint=23, outside_temperature=37, humidity=55,
                    current_setpoint=25, current_power=1100)
        self.assertEqual(estimate_energy(**args), estimate_energy(**args))
 
 
class TestComfortScore(unittest.TestCase):
    def test_unoccupied_room_always_scores_100(self):
        for sp in CANDIDATE_SETPOINTS:
            self.assertEqual(
                comfort_score(setpoint=sp, temperature=30, humidity=90, occupancy=False),
                100.0,
            )
 
    def test_setpoint_matching_room_temp_scores_highest(self):
        exact = comfort_score(setpoint=25, temperature=25, humidity=45, occupancy=True)
        far = comfort_score(setpoint=22, temperature=25, humidity=45, occupancy=True)
        self.assertGreater(exact, far)
 
    def test_high_humidity_reduces_comfort(self):
        normal = comfort_score(setpoint=24, temperature=24, humidity=50, occupancy=True)
        humid = comfort_score(setpoint=24, temperature=24, humidity=85, occupancy=True)
        self.assertLess(humid, normal)
 
    def test_score_bounded_between_0_and_100(self):
        score = comfort_score(setpoint=22, temperature=32, humidity=95, occupancy=True)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
 
    def test_comfort_score_is_deterministic(self):
        args = dict(setpoint=23, temperature=27, humidity=65, occupancy=True)
        self.assertEqual(comfort_score(**args), comfort_score(**args))
 
 
class TestOptimizeAC(unittest.TestCase):
    def test_returns_all_required_keys(self):
        result = optimize_ac(
            temperature=25, humidity=50, occupancy=True,
            current_setpoint=22, current_power=1500, outside_temperature=38,
        )
        expected_keys = {
            "recommended_setpoint", "baseline_energy", "optimized_energy",
            "saving_percent", "comfort_score", "reason",
        }
        self.assertEqual(set(result.keys()), expected_keys)
 
    def test_recommended_setpoint_is_one_of_the_candidates(self):
        result = optimize_ac(
            temperature=26, humidity=55, occupancy=True,
            current_setpoint=23, current_power=1300, outside_temperature=39,
        )
        self.assertIn(result["recommended_setpoint"], CANDIDATE_SETPOINTS)
 
    def test_deterministic_same_inputs_same_output(self):
        kwargs = dict(
            temperature=27, humidity=60, occupancy=True,
            current_setpoint=22, current_power=1400, outside_temperature=40,
        )
        r1 = optimize_ac(**kwargs)
        r2 = optimize_ac(**kwargs)
        self.assertEqual(r1, r2)
 
    def test_cold_setpoint_relative_to_room_temp_gets_raised(self):
        """User has AC set very cold (22C) while the room is already at 25C and
        occupied; a warmer, still-comfortable setpoint should win on energy."""
        result = optimize_ac(
            temperature=25, humidity=45, occupancy=True,
            current_setpoint=22, current_power=1500, outside_temperature=38,
        )
        self.assertGreater(result["recommended_setpoint"], 22)
        self.assertLessEqual(result["optimized_energy"], result["baseline_energy"])
        self.assertGreaterEqual(result["saving_percent"], 0)
 
    def test_unoccupied_room_recommends_highest_setpoint(self):
        """With nobody in the room, comfort is a non-issue, so the optimizer
        should pick the lowest-energy (highest) candidate setpoint."""
        result = optimize_ac(
            temperature=26, humidity=50, occupancy=False,
            current_setpoint=22, current_power=1500, outside_temperature=40,
        )
        self.assertEqual(result["recommended_setpoint"], max(CANDIDATE_SETPOINTS))
        self.assertEqual(result["comfort_score"], 100.0)
        self.assertIn("unoccupied", result["reason"].lower())
 
    def test_strict_comfort_threshold_falls_back_gracefully(self):
        """If the threshold is set impossibly high, the optimizer must not
        crash or silently pick something arbitrary -- it should fall back to
        the most comfortable candidate and explain why."""
        result = optimize_ac(
            temperature=25, humidity=50, occupancy=True,
            current_setpoint=24, current_power=1200, outside_temperature=36,
            min_comfort_threshold=999,
        )
        self.assertIn("no candidate setpoint reached", result["reason"].lower())
        self.assertIn(result["recommended_setpoint"], CANDIDATE_SETPOINTS)
 
    def test_baseline_matches_current_power_at_current_setpoint(self):
        result = optimize_ac(
            temperature=24, humidity=50, occupancy=True,
            current_setpoint=24, current_power=999, outside_temperature=33,
        )
        self.assertEqual(result["baseline_energy"], 999.0)
 
    def test_saving_percent_non_negative_for_feasible_recommendation(self):
        """When a feasible (comfort-satisfying) candidate is chosen, the
        recommended setpoint should never be worse (higher energy) than
        the current baseline, because 'no_change' behavior is implicitly
        included among the 5 fixed candidates whenever current_setpoint is
        one of them."""
        result = optimize_ac(
            temperature=24, humidity=50, occupancy=True,
            current_setpoint=24, current_power=1000, outside_temperature=36,
        )
        self.assertGreaterEqual(result["saving_percent"], 0)
 
    def test_custom_candidate_setpoints_are_respected(self):
        result = optimize_ac(
            temperature=24, humidity=50, occupancy=True,
            current_setpoint=24, current_power=1000, outside_temperature=36,
            candidate_setpoints=(24, 26),
        )
        self.assertIn(result["recommended_setpoint"], (24, 26))
 
 
if __name__ == "__main__":
    unittest.main(verbosity=2)
 