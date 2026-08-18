"""
test_fridge_anomaly_detector.py
----------------------------------
Unit tests for fridge_anomaly_detector.py.
 
Run with:  python -m unittest test_fridge_anomaly_detector.py -v
"""
 
import unittest
 
from fridge_anomaly_detector import (
    detect_anomaly,
    estimate_predicted_normal_power,
    estimate_unexplained_excess_ratio,
    estimate_temp_mismatch_degrees,
    compute_anomaly_score,
)
 
 
class TestEstimatePredictedNormalPower(unittest.TestCase):
    def test_zero_door_opens_and_normal_ambient_returns_historical_baseline(self):
        p = estimate_predicted_normal_power(historical_average_power=150, door_open_count=0, ambient_temperature=24)
        self.assertEqual(p, 150.0)
 
    def test_more_door_opens_increases_predicted_power(self):
        low = estimate_predicted_normal_power(150, door_open_count=1, ambient_temperature=24)
        high = estimate_predicted_normal_power(150, door_open_count=10, ambient_temperature=24)
        self.assertGreater(high, low)
 
    def test_higher_ambient_increases_predicted_power(self):
        cool = estimate_predicted_normal_power(150, door_open_count=0, ambient_temperature=24)
        hot = estimate_predicted_normal_power(150, door_open_count=0, ambient_temperature=35)
        self.assertGreater(hot, cool)
 
    def test_deterministic(self):
        args = dict(historical_average_power=140, door_open_count=5, ambient_temperature=29)
        self.assertEqual(estimate_predicted_normal_power(**args), estimate_predicted_normal_power(**args))
 
 
class TestEstimateUnexplainedExcessRatio(unittest.TestCase):
    def test_matching_predicted_power_gives_zero_ratio(self):
        r = estimate_unexplained_excess_ratio(current_power=150, predicted_normal_power=150,
                                               historical_average_power=150)
        self.assertEqual(r, 0.0)
 
    def test_positive_when_current_exceeds_predicted(self):
        r = estimate_unexplained_excess_ratio(current_power=200, predicted_normal_power=150,
                                               historical_average_power=150)
        self.assertGreater(r, 0.0)
 
    def test_negative_when_current_below_predicted(self):
        r = estimate_unexplained_excess_ratio(current_power=100, predicted_normal_power=150,
                                               historical_average_power=150)
        self.assertLess(r, 0.0)
 
    def test_zero_historical_average_avoids_division_by_zero(self):
        r = estimate_unexplained_excess_ratio(current_power=100, predicted_normal_power=0,
                                               historical_average_power=0)
        self.assertEqual(r, 0.0)
 
 
class TestEstimateTempMismatch(unittest.TestCase):
    def test_within_safe_range_returns_zero(self):
        self.assertEqual(estimate_temp_mismatch_degrees(2.5), 0.0)
        self.assertEqual(estimate_temp_mismatch_degrees(1.0), 0.0)
        self.assertEqual(estimate_temp_mismatch_degrees(4.0), 0.0)
 
    def test_too_warm_returns_positive_degrees(self):
        self.assertEqual(estimate_temp_mismatch_degrees(7.0), 3.0)
 
    def test_too_cold_returns_positive_degrees(self):
        self.assertEqual(estimate_temp_mismatch_degrees(-1.0), 2.0)
 
 
class TestComputeAnomalyScore(unittest.TestCase):
    def test_zero_inputs_gives_zero_score(self):
        total, power, temp = compute_anomaly_score(0.0, 0.0)
        self.assertEqual(total, 0.0)
        self.assertEqual(power, 0.0)
        self.assertEqual(temp, 0.0)
 
    def test_score_bounded_0_to_100(self):
        total, power, temp = compute_anomaly_score(5.0, 50.0)  # extreme, out-of-range inputs
        self.assertLessEqual(total, 100.0)
        self.assertGreaterEqual(total, 0.0)
 
    def test_power_and_temp_components_both_contribute(self):
        total, power, temp = compute_anomaly_score(0.3, 2.0)
        self.assertGreater(power, 0.0)
        self.assertGreater(temp, 0.0)
        self.assertAlmostEqual(total, round(power + temp, 2), places=2)
 
 
class TestDetectAnomaly(unittest.TestCase):
    def test_returns_all_required_keys(self):
        result = detect_anomaly(
            internal_temperature=3.0, ambient_temperature=24, door_open_count=3,
            current_power=150, historical_average_power=150,
        )
        expected_keys = {"status", "anomaly_score", "estimated_excess_energy",
                          "possible_causes", "recommendation", "details"}
        self.assertEqual(set(result.keys()), expected_keys)
 
    def test_normal_conditions_report_normal_status_and_no_causes(self):
        result = detect_anomaly(
            internal_temperature=3.0, ambient_temperature=23, door_open_count=2,
            current_power=148, historical_average_power=150,
        )
        self.assertEqual(result["status"], "NORMAL")
        self.assertEqual(result["possible_causes"], [])
        self.assertIn("no action needed", result["recommendation"].lower())
 
    def test_status_is_always_normal_or_warning(self):
        for cp in (50, 150, 300, 600):
            result = detect_anomaly(
                internal_temperature=3, ambient_temperature=25, door_open_count=3,
                current_power=cp, historical_average_power=150,
            )
            self.assertIn(result["status"], ("NORMAL", "WARNING"))
 
    def test_deterministic_same_inputs_same_output(self):
        kwargs = dict(
            internal_temperature=5, ambient_temperature=31, door_open_count=9,
            current_power=210, historical_average_power=150,
        )
        r1 = detect_anomaly(**kwargs)
        r2 = detect_anomaly(**kwargs)
        self.assertEqual(r1, r2)
 
    def test_frequent_door_opening_flagged_as_cause(self):
        result = detect_anomaly(
            internal_temperature=3, ambient_temperature=24, door_open_count=15,
            current_power=250, historical_average_power=150,
        )
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("frequent door opening", result["possible_causes"])
 
    def test_high_ambient_temperature_flagged_as_cause(self):
        result = detect_anomaly(
            internal_temperature=3, ambient_temperature=36, door_open_count=2,
            current_power=230, historical_average_power=150,
        )
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("high ambient temperature", result["possible_causes"])
 
    def test_abnormal_cooling_pattern_flagged_when_temp_out_of_safe_range(self):
        """Internal temp too warm despite power staying close to baseline --
        power alone doesn't explain the failure to cool."""
        result = detect_anomaly(
            internal_temperature=9.0, ambient_temperature=24, door_open_count=2,
            current_power=155, historical_average_power=150,
        )
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("abnormal cooling pattern", result["possible_causes"])
 
    def test_unexplained_power_excess_flagged_as_abnormal_cooling_pattern(self):
        """Power far exceeds what door-opening/ambient conditions would predict,
        with no other obvious cause -- should still surface a cause, not an
        empty list, for a WARNING status."""
        result = detect_anomaly(
            internal_temperature=3, ambient_temperature=24, door_open_count=1,
            current_power=400, historical_average_power=150,
        )
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("abnormal cooling pattern", result["possible_causes"])
 
    def test_never_claims_hardware_failure(self):
        """Hard requirement: no recommendation text may claim a confirmed
        hardware fault."""
        forbidden_phrases = ["hardware failure", "compressor failure", "compressor is broken",
                              "confirmed fault", "is broken", "has failed"]
        scenarios = [
            dict(internal_temperature=3, ambient_temperature=24, door_open_count=2,
                 current_power=150, historical_average_power=150),
            dict(internal_temperature=10, ambient_temperature=38, door_open_count=20,
                 current_power=500, historical_average_power=150),
        ]
        for kwargs in scenarios:
            result = detect_anomaly(**kwargs)
            text = result["recommendation"].lower()
            for phrase in forbidden_phrases:
                self.assertNotIn(phrase, text)
 
    def test_warning_recommendation_includes_advisory_disclaimer(self):
        result = detect_anomaly(
            internal_temperature=9, ambient_temperature=35, door_open_count=15,
            current_power=300, historical_average_power=150,
        )
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("advisory estimate", result["recommendation"].lower())
 
    def test_estimated_excess_energy_matches_simple_difference(self):
        result = detect_anomaly(
            internal_temperature=3, ambient_temperature=24, door_open_count=2,
            current_power=210, historical_average_power=150,
        )
        self.assertEqual(result["estimated_excess_energy"], 60.0)
 
    def test_estimated_excess_energy_can_be_negative(self):
        """Power below the historical baseline is a valid (and informative)
        output, not clamped to zero -- it may pair with a temp mismatch to
        reveal an under-cooling pattern."""
        result = detect_anomaly(
            internal_temperature=8, ambient_temperature=24, door_open_count=2,
            current_power=100, historical_average_power=150,
        )
        self.assertLess(result["estimated_excess_energy"], 0)
 
    def test_custom_warning_threshold_is_respected(self):
        result = detect_anomaly(
            internal_temperature=3, ambient_temperature=24, door_open_count=2,
            current_power=155, historical_average_power=150,
            warning_threshold=1.0,  # extremely strict
        )
        self.assertEqual(result["status"], "WARNING")
 
 
if __name__ == "__main__":
    unittest.main(verbosity=2)
 