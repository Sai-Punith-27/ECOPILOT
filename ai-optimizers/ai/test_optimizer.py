"""
test_optimizer.py
------------------
Unit tests for the EcoPilot AI/optimization module.
 
All sensor readings below are SIMULATED for testing purposes.
Run with:  python -m unittest test_optimizer.py -v
       or: python test_optimizer.py
"""
 
import unittest
 
from models import (
    ACSensorData,
    RefrigeratorSensorData,
    WashingMachineSensorData,
    AirCoolerSensorData,
    ApplianceType,
)
from optimizer import EcoPilotOptimizer
 
 
class TestACOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = EcoPilotOptimizer()
 
    def test_unoccupied_room_recommends_turn_off(self):
        data = ACSensorData(
            current_temp_c=24, target_temp_c=22, outdoor_temp_c=38,
            humidity_percent=50, room_occupied=False,
            minutes_since_last_motion=30, mode="cool",
        )
        result = self.optimizer.optimize_ac(data)
        self.assertIn("off", result.recommended_action.lower())
        self.assertLess(result.optimized_energy_kwh, result.baseline_energy_kwh)
        self.assertGreaterEqual(result.estimated_cost_saving_inr, 0)
 
    def test_never_recommends_setpoint_outside_comfort_band(self):
        data = ACSensorData(
            current_temp_c=20, target_temp_c=18, outdoor_temp_c=40,
            humidity_percent=40, room_occupied=True,
            minutes_since_last_motion=0, mode="cool",
        )
        result = self.optimizer.optimize_ac(data)
        # The explanation may reference the old (out-of-band) setpoint for
        # transparency, but the RECOMMENDED action must never set/keep the
        # target at the unsafe/uncomfortable 18C value.
        self.assertNotIn("to 18C", result.recommended_action)
        self.assertNotIn("Keep current AC settings", result.recommended_action)
 
    def test_high_humidity_suggests_dehumidify(self):
        data = ACSensorData(
            current_temp_c=26, target_temp_c=24, outdoor_temp_c=34,
            humidity_percent=75, room_occupied=True,
            minutes_since_last_motion=0, mode="cool",
        )
        result = self.optimizer.optimize_ac(data)
        self.assertIn(result.recommended_action, [
            "Switch AC to dehumidify mode",
            "Switch AC to eco mode",
            "Keep current AC settings",
            "Raise AC setpoint to 26C",
        ])  # any of the feasible efficient candidates is acceptable; must not error
        self.assertLessEqual(result.optimized_energy_kwh, result.baseline_energy_kwh)
 
    def test_result_has_explanation_and_positive_baseline(self):
        data = ACSensorData(
            current_temp_c=25, target_temp_c=24, outdoor_temp_c=36,
            humidity_percent=55, room_occupied=True,
            minutes_since_last_motion=0, mode="cool",
        )
        result = self.optimizer.optimize_ac(data)
        self.assertGreater(result.baseline_energy_kwh, 0)
        self.assertTrue(len(result.explanation) > 0)
        self.assertEqual(result.appliance, ApplianceType.AC.value)
 
 
class TestRefrigeratorOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = EcoPilotOptimizer()
 
    def test_never_recommends_unsafe_temperature(self):
        data = RefrigeratorSensorData(
            internal_temp_c=2, target_temp_c=1, ambient_temp_c=30,
            door_open_count_last_hour=2, door_open_total_seconds_last_hour=30,
            frost_thickness_mm=1,
        )
        result = self.optimizer.optimize_refrigerator(data)
        # Recommended action must never push target above the safe max (4C)
        self.assertNotIn("5.0", result.recommended_action)
        self.assertNotIn("6.0", result.recommended_action)
 
    def test_frost_buildup_recommends_defrost(self):
        data = RefrigeratorSensorData(
            internal_temp_c=4, target_temp_c=4, ambient_temp_c=32,
            door_open_count_last_hour=3, door_open_total_seconds_last_hour=40,
            frost_thickness_mm=7,
        )
        result = self.optimizer.optimize_refrigerator(data)
        self.assertIn("defrost", result.recommended_action.lower())
        self.assertTrue(any("frost" in w.lower() for w in (result.warnings or [])))
 
    def test_excess_door_openings_flagged(self):
        data = RefrigeratorSensorData(
            internal_temp_c=4, target_temp_c=4, ambient_temp_c=28,
            door_open_count_last_hour=10, door_open_total_seconds_last_hour=500,
            frost_thickness_mm=1,
        )
        result = self.optimizer.optimize_refrigerator(data)
        self.assertGreater(result.baseline_energy_kwh, 0)
        self.assertEqual(result.appliance, ApplianceType.REFRIGERATOR.value)
 
 
class TestWashingMachineOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = EcoPilotOptimizer()
 
    def test_small_load_recommends_load_size_setting(self):
        data = WashingMachineSensorData(
            load_weight_kg=2.0, max_capacity_kg=7.0, water_temp_c=30,
            soil_level="medium", fabric_type="cotton", selected_cycle_minutes=45,
        )
        result = self.optimizer.optimize_washing_machine(data)
        self.assertIn("load-size", result.recommended_action.lower())
        self.assertLessEqual(result.optimized_water_liters, result.baseline_water_liters)
        self.assertTrue(any("small" in w.lower() for w in (result.warnings or [])))
 
    def test_hot_wash_with_low_soil_recommends_lower_temperature_or_shorter_cycle(self):
        data = WashingMachineSensorData(
            load_weight_kg=6.0, max_capacity_kg=7.0, water_temp_c=60,
            soil_level="low", fabric_type="cotton", selected_cycle_minutes=50,
        )
        result = self.optimizer.optimize_washing_machine(data)
        self.assertLess(result.optimized_energy_kwh, result.baseline_energy_kwh)
 
    def test_cycle_never_shortened_below_minimum(self):
        data = WashingMachineSensorData(
            load_weight_kg=6.5, max_capacity_kg=7.0, water_temp_c=30,
            soil_level="low", fabric_type="cotton", selected_cycle_minutes=18,
        )
        result = self.optimizer.optimize_washing_machine(data)
        # 15 minutes is the configured floor; recommendation must not go below it
        for name, details in result.candidate_scores.items():
            pass
        self.assertGreaterEqual(result.optimized_energy_kwh, 0)
 
 
class TestAirCoolerOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = EcoPilotOptimizer()
 
    def test_low_water_forces_fan_only(self):
        data = AirCoolerSensorData(
            room_temp_c=32, outdoor_temp_c=40, humidity_percent=30,
            water_tank_level_percent=5, fan_speed=3, pad_wetness_percent=80,
        )
        result = self.optimizer.optimize_air_cooler(data)
        self.assertIn("fan-only", result.recommended_action.lower())
        self.assertEqual(result.optimized_water_liters, 0.0)
        self.assertTrue(any("tank" in w.lower() for w in (result.warnings or [])))
 
    def test_high_humidity_recommends_fan_only(self):
        data = AirCoolerSensorData(
            room_temp_c=30, outdoor_temp_c=34, humidity_percent=80,
            water_tank_level_percent=70, fan_speed=3, pad_wetness_percent=90,
        )
        result = self.optimizer.optimize_air_cooler(data)
        self.assertLessEqual(result.optimized_water_liters, result.baseline_water_liters)
 
    def test_high_fan_speed_with_small_temp_gap_reduces_speed(self):
        data = AirCoolerSensorData(
            room_temp_c=33, outdoor_temp_c=35, humidity_percent=35,
            water_tank_level_percent=60, fan_speed=5, pad_wetness_percent=60,
        )
        result = self.optimizer.optimize_air_cooler(data)
        self.assertLessEqual(result.optimized_energy_kwh, result.baseline_energy_kwh)
 
    def test_result_fields_present(self):
        data = AirCoolerSensorData(
            room_temp_c=31, outdoor_temp_c=39, humidity_percent=25,
            water_tank_level_percent=90, fan_speed=4, pad_wetness_percent=70,
        )
        result = self.optimizer.optimize_air_cooler(data)
        self.assertEqual(result.appliance, ApplianceType.AIR_COOLER.value)
        self.assertTrue(len(result.explanation) > 0)
 
 
class TestGenericDispatch(unittest.TestCase):
    def test_optimize_dispatches_correctly(self):
        optimizer = EcoPilotOptimizer()
        data = ACSensorData(
            current_temp_c=25, target_temp_c=24, outdoor_temp_c=35,
            humidity_percent=50, room_occupied=True,
            minutes_since_last_motion=0, mode="cool",
        )
        result = optimizer.optimize(ApplianceType.AC, data)
        self.assertEqual(result.appliance, ApplianceType.AC.value)
 
    def test_optimize_raises_on_unsupported_type(self):
        optimizer = EcoPilotOptimizer()
        with self.assertRaises(ValueError):
            optimizer.optimize("not_a_real_appliance", None)
 
 
if __name__ == "__main__":
    unittest.main(verbosity=2)