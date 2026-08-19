"""Unit tests for the deterministic smart recommendation builder."""

import copy
import unittest

from energy_recommendations import build_energy_recommendations



def sample_inputs():
    raw_readings = {
        "ac": {
            "temperature": 28.0,
            "humidity": 55.0,
            "occupancy": True,
            "setpoint": 22.0,
            "power_watts": 1600.0,
        },
        "fridge": {
            "temperature": 3.0,
            "power_watts": 40.0,
        },
        "washer": {
            "cycle": "WASHING",
            "load_kg": 4.0,
            "power_watts": 800.0,
        },
        "cooler": {
            "temperature": 32.0,
            "humidity": 45.0,
            "water_level": 70.0,
            "pump_duty": 50.0,
            "power_watts": 100.0,
            "occupancy": True,
        },
    }
    household_report = {
        "recommendations": [
            {
                "appliance": "ac",
                "recommendation": "Set AC to 25C",
                "baseline_energy_kwh": 1.6,
                "optimized_energy_kwh": 1.4,
            },
            {
                "appliance": "refrigerator",
                "recommendation": "Raise setpoint to 4.0C",
                "baseline_energy_kwh": 5.0,
                "optimized_energy_kwh": 4.7,
            },
            {
                "appliance": "washing_machine",
                "recommendation": "Use Eco mode",
                "baseline_energy_kwh": 1.0,
                "optimized_energy_kwh": 0.65,
            },
            {
                "appliance": "cooler",
                "recommendation": "Set fan speed 3, pump duty 25%",
                "baseline_energy_kwh": 0.1,
                "optimized_energy_kwh": 0.07,
            },
        ]
    }
    fridge_anomaly = {"status": "NORMAL", "anomaly_score": 0.0}
    dryrun_info = (False, None, None)
    return raw_readings, household_report, fridge_anomaly, dryrun_info



class TestSmartEnergyRecommendations(unittest.TestCase):
    def test_returns_one_record_per_appliance_with_required_fields(self):
        result = build_energy_recommendations(*sample_inputs())

        self.assertEqual(
            [r["appliance"] for r in result["recommendations"]],
            ["ac", "refrigerator", "washing_machine", "cooler"],
        )
        for recommendation in result["recommendations"]:
            self.assertTrue(recommendation["appliance_name"])
            self.assertTrue(recommendation["observation"])
            self.assertTrue(recommendation["action"])
            self.assertTrue(recommendation["impact"])
            self.assertIn(recommendation["priority"], ("Low", "Medium", "High"))

    def test_output_is_deterministic(self):
        inputs = sample_inputs()
        first = build_energy_recommendations(*copy.deepcopy(inputs))
        second = build_energy_recommendations(*copy.deepcopy(inputs))
        self.assertEqual(first, second)

    def test_ac_unoccupied_runtime_is_high_priority_without_fake_savings(self):
        raw, report, anomaly, dryrun = sample_inputs()
        raw["ac"].update({"occupancy": False, "power_watts": 1700.0})

        ac = build_energy_recommendations(raw, report, anomaly, dryrun)["recommendations"][0]

        self.assertEqual(ac["priority"], "High")
        self.assertIn("unoccupied", ac["observation"])
        self.assertIn("off", ac["action"].lower())
        self.assertIsNone(ac["estimated_energy_saving_kwh"])

    def test_refrigerator_warning_is_high_priority_and_advisory(self):
        raw, report, _, dryrun = sample_inputs()
        anomaly = {
            "status": "WARNING",
            "anomaly_score": 82.0,
            "recommendation": "Monitor the refrigerator and consider a professional inspection.",
        }

        fridge = build_energy_recommendations(raw, report, anomaly, dryrun)["recommendations"][1]

        self.assertEqual(fridge["priority"], "High")
        self.assertIn("unusual", fridge["observation"])
        self.assertIn("inspection", fridge["action"])
        self.assertIsNone(fridge["estimated_energy_saving_kwh"])

    def test_fridge_temperature_outside_advisory_band_is_not_hardware_diagnosis(self):
        raw, report, anomaly, dryrun = sample_inputs()
        raw["fridge"]["temperature"] = 4.5

        fridge = build_energy_recommendations(raw, report, anomaly, dryrun)["recommendations"][1]

        self.assertEqual(fridge["priority"], "Medium")
        self.assertIn("illustrative 1–4°C safe range", fridge["observation"])
        self.assertIn("monitoring", fridge["action"])

    def test_washer_idle_state_uses_qualitative_impact(self):
        raw, report, anomaly, dryrun = sample_inputs()
        raw["washer"] = {"cycle": "IDLE", "load_kg": 0.0, "power_watts": 0.0}

        washer = build_energy_recommendations(raw, report, anomaly, dryrun)["recommendations"][2]

        self.assertEqual(washer["priority"], "Low")
        self.assertIn("idle", washer["observation"])
        self.assertIn("Qualitative", washer["impact"])
        self.assertIsNone(washer["estimated_energy_saving_kwh"])

    def test_cooler_dry_run_takes_priority_over_energy_estimate(self):
        raw, report, anomaly, _ = sample_inputs()
        cooler = build_energy_recommendations(raw, report, anomaly, (True, 45.0, 0.0))["recommendations"][3]

        self.assertEqual(cooler["priority"], "High")
        self.assertIn("dry-run", cooler["observation"])
        self.assertIn("water feed", cooler["action"])
        self.assertIsNone(cooler["estimated_energy_saving_kwh"])

    def test_numeric_savings_are_copied_from_optimizer_and_timeframe_labeled(self):
        result = build_energy_recommendations(*sample_inputs())
        recommendations = {r["appliance"]: r for r in result["recommendations"]}

        self.assertEqual(recommendations["ac"]["estimated_energy_saving_kwh"], 0.2)
        self.assertIn("hour-equivalent", recommendations["ac"]["impact"])
        self.assertEqual(recommendations["refrigerator"]["estimated_energy_saving_kwh"], 0.3)
        self.assertIn("day", recommendations["refrigerator"]["impact"])
        self.assertEqual(result["summary"]["estimated_energy_saving_kwh"], 0.88)
        self.assertEqual(result["summary"]["opportunity_count"], 4)

    def test_missing_ml_predictions_do_not_change_rule_based_recommendations(self):
        raw, report, anomaly, dryrun = sample_inputs()
        without_ml = build_energy_recommendations(raw, report, anomaly, dryrun)
        with_unavailable_ml = build_energy_recommendations(
            raw,
            report,
            anomaly,
            dryrun,
            {"ac_01": {"model_available": False}, "cooler_01": {"model_available": False}},
        )

        self.assertEqual(without_ml["recommendations"], with_unavailable_ml["recommendations"])
        self.assertIsNone(with_unavailable_ml["summary"]["ml_context"])

    def test_available_ml_is_labeled_as_household_context(self):
        raw, report, anomaly, dryrun = sample_inputs()
        result = build_energy_recommendations(
            raw,
            report,
            anomaly,
            dryrun,
            {"ac_01": {"model_available": True}, "cooler_01": {"model_available": True}},
        )

        self.assertIn("whole-household", result["summary"]["ml_context"])
        self.assertIn("AC", result["summary"]["ml_context"])
        self.assertIn("Desert Cooler", result["summary"]["ml_context"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
