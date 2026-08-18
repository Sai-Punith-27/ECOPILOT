"""
EcoPilot Frontend: Consumer View
====================================
A homeowner-friendly rendering of the same live data the technical
dashboard uses -- plain language, big friendly status indicators, no
raw telemetry dumps, no technical assumption notes. Meant to be what an
actual user would see day-to-day, as opposed to the Technical View
(judges/developers), which shows the full methodology and raw data.

Nothing here computes anything new -- it takes the SAME household_report,
fridge_anomaly, dryrun_info, etc. already produced by the optimizer
pipeline in app.py and just presents them differently.
"""

import streamlit as st


APPLIANCE_ICON = {"ac": "❄️", "refrigerator": "🧊", "washing_machine": "🧺", "cooler": "🌀"}
APPLIANCE_FRIENDLY_NAME = {"ac": "Air Conditioner", "refrigerator": "Refrigerator",
                           "washing_machine": "Washing Machine", "cooler": "Desert Cooler"}


def _score_label(score):
    if score >= 85:
        return "Excellent", "🟢"
    elif score >= 65:
        return "Good", "🟡"
    elif score >= 40:
        return "Fair", "🟠"
    else:
        return "Needs Attention", "🔴"


def _simplify_recommendation(rec):
    """Turn a technical recommendation string into a short, friendly action line."""
    text = rec["recommendation"]
    # Recommendations from the optimizers already read fairly plainly
    # (e.g. "Set AC to 23C", "Use Normal mode") -- just present them as
    # a friendly suggestion rather than a lab report.
    return text


def render_consumer_view(household_report, fridge_anomaly, raw_readings, outside_temp,
                          weather_source, dryrun_info, washer_advice):
    e = household_report["energy"]
    w = household_report["water"]
    cst = household_report["cost"]
    carbon = household_report["carbon"]
    score = household_report["resource_score"]
    label, emoji = _score_label(score)

    has_alert = (fridge_anomaly["status"] == "WARNING") or dryrun_info[0]

    # ---- Big overall status ----
    if has_alert:
        st.markdown("## 🏠 A couple of things need your attention")
    else:
        st.markdown("## 🏠 Your home is running efficiently")

    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(f"### {emoji} {label}")
        st.caption("Overall home efficiency")
    with col2:
        st.markdown(
            f"**Today's impact so far:** saving **₹{cst['saving_inr']:.2f}**, "
            f"**{w['saving_liters']:.1f} liters** of water, and reducing "
            f"CO₂ by **{carbon['saving_kg']:.2f} kg** compared to unoptimized settings."
        )
        st.caption(f"It's {outside_temp:.0f}°C outside right now.")

    st.divider()

    # ---- Alerts, in plain language ----
    if fridge_anomaly["status"] == "WARNING":
        st.error(
            "🧊 **Your refrigerator is using more power than usual.** "
            "This could mean the door isn't sealing properly, it's overdue for cleaning, "
            "or it may need a checkup. Worth a look today."
        )
    dryrun_flag = dryrun_info[0]
    if dryrun_flag:
        st.error(
            "🌀 **Your desert cooler's fan is running but barely any water is being used.** "
            "The water tank might be empty, or the pump could be stuck. Check it soon to "
            "avoid damaging the cooling pads."
        )
    if washer_advice and washer_advice["should_wait"]:
        st.info(f"🧺 **Tip:** electricity is a bit more expensive right now — "
                f"if your laundry can wait, running it later tonight could cost less.")

    st.divider()

    # ---- Per-appliance friendly cards ----
    st.markdown("### Your Appliances")
    cols = st.columns(4)
    for i, rec in enumerate(household_report["recommendations"]):
        appliance = rec["appliance"]
        with cols[i]:
            icon = APPLIANCE_ICON.get(appliance, "🔌")
            name = APPLIANCE_FRIENDLY_NAME.get(appliance, appliance.replace("_", " ").title())
            is_flagged = (appliance == "refrigerator" and fridge_anomaly["status"] == "WARNING") or \
                         (appliance == "cooler" and dryrun_flag)
            status_icon = "⚠️" if is_flagged else "✅"
            st.markdown(f"#### {icon} {name} {status_icon}")
            st.write(_simplify_recommendation(rec))
            energy_saved = rec["baseline_energy_kwh"] - rec["optimized_energy_kwh"]
            if energy_saved > 0.001:
                st.caption(f"💡 Saving ~{energy_saved:.3f} kWh right now")

    st.divider()
    st.caption(
        "This is a simplified view for everyday use. Switch to **Technical View** above "
        "for the full data, methodology, and live readings."
    )
