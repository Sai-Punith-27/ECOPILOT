"""
EcoPilot Frontend: Time-of-Day Tariff Scheduling
=====================================================
HONESTY NOTE: India does not have one single national real-time ToD
tariff API -- rates vary by state/DISCOM and change periodically via
regulatory filings. This module uses an ILLUSTRATIVE tariff schedule
(typical shape reported by several Indian state ToD tariff orders: a
peak surcharge in the evening, a discount in late-night/early-morning
off-peak hours), not a live feed. Labeled as such in the UI. Swapping in
a real per-DISCOM tariff API later would only require changing
`get_current_slot()`.
"""

from datetime import datetime

# Illustrative only -- see module docstring.
TOD_SCHEDULE = [
    # (start_hour, end_hour, label, rate_multiplier)
    (0, 6, "Off-Peak (night)", 0.80),
    (6, 9, "Normal", 1.00),
    (9, 18, "Normal", 1.00),
    (18, 22, "Peak (evening)", 1.25),
    (22, 24, "Off-Peak (night)", 0.80),
]

BASE_RATE_INR_PER_KWH = 7.0  # matches ai-optimizers/ai/calculations.py's illustrative rate


def get_current_slot(now=None):
    now = now or datetime.now()
    hour = now.hour
    for start, end, label, mult in TOD_SCHEDULE:
        if start <= hour < end:
            return {"label": label, "multiplier": mult, "rate_inr_per_kwh": BASE_RATE_INR_PER_KWH * mult}
    return {"label": "Normal", "multiplier": 1.0, "rate_inr_per_kwh": BASE_RATE_INR_PER_KWH}


def get_next_offpeak_window(now=None):
    """Returns a short human-readable string for the next off-peak window."""
    now = now or datetime.now()
    hour = now.hour
    if hour < 22:
        return "10:00 PM – 6:00 AM"
    else:
        return "now – 6:00 AM"


def washing_machine_schedule_advice(current_cycle, now=None):
    slot = get_current_slot(now)
    if current_cycle and current_cycle.upper() not in ("IDLE", "COMPLETE"):
        return None  # already running, nothing to schedule
    if slot["multiplier"] <= 1.0:
        return {
            "message": f"Currently in **{slot['label']}** pricing (₹{slot['rate_inr_per_kwh']:.2f}/kWh) — a good time to run the washing machine.",
            "should_wait": False,
        }
    else:
        next_window = get_next_offpeak_window(now)
        savings_pct = (1 - (BASE_RATE_INR_PER_KWH * 0.80) / slot["rate_inr_per_kwh"]) * 100
        return {
            "message": f"Currently in **{slot['label']}** pricing (₹{slot['rate_inr_per_kwh']:.2f}/kWh). "
                       f"Waiting until **{next_window}** (off-peak) could cost ~{savings_pct:.0f}% less per kWh.",
            "should_wait": True,
        }
