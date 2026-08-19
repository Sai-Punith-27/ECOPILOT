"""
EcoPilot Frontend — Live Dashboard
======================================
Run with: streamlit run app.py   (from inside the frontend/ folder)

Pulls LIVE telemetry from the real EcoPilot backend (../backend/backend,
fed by ../backend/simulator), maps it into the inputs each AI optimizer
module (../ai-optimizers/ai) needs, and displays live recommendations:
optimal AC setpoint, cooler fan/pump setting, washing-machine mode,
fridge anomaly status, plus household-level energy/water/cost/carbon
savings and a resource efficiency score.

Also includes:
  - Live trend charts (power/water over the monitoring session)
  - Cooler pump dry-run fault detection (rule-based on live telemetry)
  - Time-of-day tariff-aware washing-machine scheduling advice
  - Vision diagnostics tab (photo-based frost/dirt/scale checks)

IMPORTANT — assumptions this dashboard fills in (read this before demoing):
The telemetry schema reports what each appliance itself knows (its own
temperature, power draw, etc.) but does NOT include a few fields the
optimizers need for context they can't self-report:
  - outside_temperature / ambient_temperature: fetched from a real, free
    weather API (Open-Meteo, no key required). Falls back to a fixed
    default if unreachable.
  - dirt_level, water_hardness, deadline_minutes (washing machine): these
    are inherently things a PERSON decides when starting a wash, not
    something a sensor reports -- exposed as sidebar inputs with sensible
    defaults, not fabricated as sensor data.
  - historical_average_power, door_open_count (fridge anomaly): computed
    live from the readings collected during this monitoring session.
  - occupancy for the cooler: the telemetry schema only has an occupancy
    field for the AC; the cooler's own occupancy is assumed to match the
    AC's, documented here rather than silently guessed.
  - time-of-day tariff schedule: illustrative (typical shape of Indian
    state ToD orders), not a live per-DISCOM feed -- see tariff.py.
"""

import sys
import os
import time

_FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
_AI_OPTIMIZERS_DIR = os.path.join(os.path.dirname(_FRONTEND_DIR), "ai-optimizers", "ai")
sys.path.insert(0, _FRONTEND_DIR)
sys.path.insert(0, _AI_OPTIMIZERS_DIR)

import streamlit as st
import plotly.graph_objects as go
from PIL import Image

# Bridge Streamlit Community Cloud's Secrets to a plain env var, so the
# same BACKEND_BASE_URL lookup works whether running locally (.env / shell
# export) or deployed on Streamlit Cloud (Settings -> Secrets).
try:
    if "BACKEND_BASE_URL" in st.secrets:
        os.environ["BACKEND_BASE_URL"] = st.secrets["BACKEND_BASE_URL"]
except Exception:
    pass  # no secrets.toml present (e.g. local run) -- fine, falls back to env var / default

from backend_client import (
    check_backend_alive, get_all_appliances_latest, get_energy_prediction,
    APPLIANCE_IDS, APPLIANCE_LABELS, DEFAULT_BASE_URL
)
from weather_client import get_outside_conditions, DEFAULT_LAT, DEFAULT_LON
from tariff import get_current_slot, washing_machine_schedule_advice
from vision_diagnostics import ANALYZERS
from consumer_view import render_consumer_view, render_smart_recommendations
from energy_recommendations import build_energy_recommendations

from household_optimizer import optimize_household
from fridge_anomaly_detector import detect_anomaly

st.set_page_config(page_title="EcoPilot Live Dashboard", layout="wide")

st.title("🌿 EcoPilot — Live Resource Optimization Dashboard")
st.caption(
    "Live per-appliance telemetry from the real EcoPilot backend, fed through the team's AI "
    "optimizer modules for real-time energy/water/cost/carbon recommendations."
)

view_mode = st.radio(
    "View",
    ["🏠 Simple View (for homeowners)", "⚙️ Technical View (full data & methodology)"],
    horizontal=True,
    label_visibility="collapsed",
)
is_simple = view_mode.startswith("🏠")

tab_dash, tab_vision = st.tabs(["📊 Live Dashboard", "📷 Vision Diagnostics"])

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.header("🔌 Backend Connection")
    base_url = st.text_input("Backend URL", value=DEFAULT_BASE_URL)
    st.caption("Connection status shown automatically above the dashboard.")

    st.divider()
    st.header("🌤️ Weather Location")
    st.caption("Used for outside/ambient temperature — the telemetry schema doesn't carry this.")
    lat = st.number_input("Latitude", value=DEFAULT_LAT, format="%.4f")
    lon = st.number_input("Longitude", value=DEFAULT_LON, format="%.4f")

    st.divider()
    st.header("🧺 Washing Machine Context")
    st.caption("These are decisions a person makes when starting a wash — not sensor data.")
    dirt_level = st.selectbox("Dirt level", ["light", "medium", "heavy"], index=1)
    water_hardness = st.slider("Water hardness (0=soft, 100=hard)", 0, 100, 50)
    deadline_minutes = st.slider("Must finish within (minutes)", 15, 180, 60)

    st.divider()
    poll_interval = st.slider("Refresh interval (seconds)", 2, 10, 3)

# ============================================================
# SESSION STATE
# ============================================================
if "wm_energy_baseline" not in st.session_state:
    st.session_state["wm_energy_baseline"] = 1.0

if "fridge_history" not in st.session_state:
    st.session_state["fridge_history"] = {"powers": [], "door_open_count": 0, "last_door_state": None}

if "trend_history" not in st.session_state:
    st.session_state["trend_history"] = {aid: {"power": [], "water": []} for aid in APPLIANCE_IDS}

if "cooler_dryrun_history" not in st.session_state:
    st.session_state["cooler_dryrun_history"] = {"pump_duty": [], "water_liters": []}


def update_trend_history(raw_readings_by_id):
    for aid in APPLIANCE_IDS:
        r = raw_readings_by_id.get(aid, {})
        hist = st.session_state["trend_history"][aid]
        hist["power"].append(r.get("power_watts") if r else None)
        hist["water"].append(r.get("water_liters") if r else None)
        hist["power"] = hist["power"][-60:]
        hist["water"] = hist["water"][-60:]


def check_cooler_dryrun(cooler_latest):
    """Rule-based fault check: pump reports a nonzero duty cycle (should
    be actively drawing water) but water consumption over the last few
    readings is ~0 -- exactly the dry-run pattern from the NILM prototype,
    now applied directly to real per-appliance telemetry instead of an
    inferred aggregate signal."""
    h = st.session_state["cooler_dryrun_history"]
    pump = cooler_latest.get("pump_duty")
    water = cooler_latest.get("water_liters")
    if pump is not None:
        h["pump_duty"].append(pump)
        h["pump_duty"] = h["pump_duty"][-6:]
    if water is not None:
        h["water_liters"].append(water)
        h["water_liters"] = h["water_liters"][-6:]

    if len(h["pump_duty"]) >= 5 and len(h["water_liters"]) >= 5:
        avg_pump = sum(h["pump_duty"]) / len(h["pump_duty"])
        total_water = sum(h["water_liters"])
        if avg_pump > 10 and total_water < 0.05:
            return True, avg_pump, total_water
    return False, None, None


def map_and_optimize(latest, outside_temp, outside_humidity):
    ac_readings = latest.get("ac_01", [])
    fridge_readings = latest.get("fridge_01", [])
    washer_readings = latest.get("washer_01", [])
    cooler_readings = latest.get("cooler_01", [])

    ac_latest = ac_readings[0] if ac_readings else {}
    fridge_latest = fridge_readings[0] if fridge_readings else {}
    washer_latest = washer_readings[0] if washer_readings else {}
    cooler_latest = cooler_readings[0] if cooler_readings else {}

    fh = st.session_state["fridge_history"]
    if fridge_latest.get("power_watts") is not None:
        fh["powers"].append(fridge_latest["power_watts"])
        fh["powers"] = fh["powers"][-100:]
    door_now = fridge_latest.get("door_open")
    if door_now is True and fh["last_door_state"] is not True:
        fh["door_open_count"] += 1
    fh["last_door_state"] = door_now
    historical_average_power = (sum(fh["powers"]) / len(fh["powers"])) if fh["powers"] else (
        fridge_latest.get("power_watts", 40.0)
    )

    ac_state = {
        "temperature": ac_latest.get("temperature", 28.0),
        "humidity": ac_latest.get("humidity", 55.0),
        "occupancy": ac_latest.get("occupancy", True),
        "current_setpoint": ac_latest.get("setpoint", 24.0),
        "current_power": ac_latest.get("power_watts", 1000.0),
        "outside_temperature": outside_temp,
    }
    fridge_state = {
        "internal_temperature": fridge_latest.get("temperature", 4.0),
        "target_temperature": fridge_latest.get("temperature", 4.0),
        "ambient_temperature": outside_temp,
        "door_open_count": fh["door_open_count"],
    }
    washer_state = {
        "load_kg": washer_latest.get("load_kg", 4.0),
        "dirt_level": dirt_level,
        "water_hardness": water_hardness,
        "current_cycle": washer_latest.get("cycle", "normal") or "normal",
        "current_water": washer_latest.get("water_liters", 0.0) or 0.0,
        "current_energy": st.session_state["wm_energy_baseline"],
        "deadline_minutes": deadline_minutes,
    }
    cooler_state = {
        "temperature": cooler_latest.get("temperature", 30.0),
        "humidity": cooler_latest.get("humidity", 40.0),
        "occupancy": ac_latest.get("occupancy", True),
        "water_level": cooler_latest.get("water_level", 80.0),
        "fan_speed": cooler_latest.get("fan_speed", 3),
        "pump_duty": cooler_latest.get("pump_duty", 40.0),
        "power": cooler_latest.get("power_watts", 100.0),
    }

    household_report = optimize_household(
        ac=ac_state, refrigerator=fridge_state, washing_machine=washer_state, cooler=cooler_state
    )
    fridge_anomaly = detect_anomaly(
        internal_temperature=fridge_latest.get("temperature", 4.0),
        ambient_temperature=outside_temp,
        door_open_count=fh["door_open_count"],
        current_power=fridge_latest.get("power_watts", 40.0),
        historical_average_power=historical_average_power,
    )
    dryrun_flag, avg_pump, total_water = check_cooler_dryrun(cooler_latest)

    raw = {"ac": ac_latest, "fridge": fridge_latest, "washer": washer_latest, "cooler": cooler_latest}
    update_trend_history({"ac_01": ac_latest, "fridge_01": fridge_latest, "washer_01": washer_latest, "cooler_01": cooler_latest})

    return household_report, fridge_anomaly, raw, (dryrun_flag, avg_pump, total_water)


# Only ac_01 and cooler_01 currently report BOTH temperature and humidity
# telemetry -- the two fields the ML model's indoor-conditions features
# need. fridge_01 (no humidity sensor) and washer_01 (no temperature/
# humidity sensors) genuinely can't supply them, so we don't call
# predict for those two rather than fabricating fake sensor values.
ML_SUPPORTED_APPLIANCE_IDS = ["ac_01", "cooler_01"]


def fetch_ml_predictions(base_url):
    """
    Calls the backend's /api/predict route for each ML-supported appliance.
    Never raises (get_energy_prediction already guarantees this) -- any
    unreachable/unavailable case just comes back with model_available=False
    and is rendered as a plain fallback message, not an error.
    """
    return {aid: get_energy_prediction(aid, base_url=base_url) for aid in ML_SUPPORTED_APPLIANCE_IDS}


def render_trend_charts():
    st.subheader("📈 Live Trends (this session)")
    hist = st.session_state["trend_history"]
    cols = st.columns(4)
    labels = {"ac_01": "AC Power (W)", "fridge_01": "Fridge Power (W)",
              "washer_01": "Washer Water (L, cumulative)", "cooler_01": "Cooler Power (W)"}
    for i, aid in enumerate(APPLIANCE_IDS):
        with cols[i]:
            series = hist[aid]["water"] if aid == "washer_01" else hist[aid]["power"]
            series = [v for v in series if v is not None]
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=series, mode="lines", line=dict(width=2)))
            fig.update_layout(height=180, margin=dict(l=10, r=10, t=30, b=10), title=labels[aid],
                               title_font_size=12, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key=f"trend_{aid}_{len(series)}")


def render_snapshot(household_report, fridge_anomaly, raw_readings, outside_temp, outside_humidity, weather_source, dryrun_info, ml_predictions=None, smart_report=None):
    st.caption(f"🌤️ Outside conditions: {outside_temp:.1f}°C"
               + (f", {outside_humidity:.0f}% RH" if outside_humidity is not None else "")
               + f"  ·  _{weather_source}_")

    slot = get_current_slot()
    st.caption(f"⏰ Time-of-day tariff: **{slot['label']}** — ₹{slot['rate_inr_per_kwh']:.2f}/kWh "
               f"_(illustrative schedule, not a live DISCOM feed — see tariff.py)_")

    st.subheader("📊 Household Summary")
    c1, c2, c3, c4, c5 = st.columns(5)
    e, w, cst, carbon = household_report["energy"], household_report["water"], household_report["cost"], household_report["carbon"]
    c1.metric("Energy saving", f"{e['saving_kwh']:.3f} kWh", f"-{e['saving_kwh']:.3f}")
    c2.metric("Water saving", f"{w['saving_liters']:.2f} L", f"-{w['saving_liters']:.2f}")
    c3.metric("Cost saving", f"₹{cst['saving_inr']:.2f}", f"-₹{cst['saving_inr']:.2f}")
    c4.metric("Carbon saving", f"{carbon['saving_kg']:.3f} kg CO₂", f"-{carbon['saving_kg']:.3f}")
    c5.metric("Resource score", f"{household_report['resource_score']:.0f}/100")

    if ml_predictions:
        st.subheader("🤖 ML Energy Prediction")
        st.caption(
            "Predicts approximate WHOLE-HOUSEHOLD appliance energy (Wh, ~10-minute-interval "
            "scale) from live indoor + outdoor conditions — trained on the UCI Appliances "
            "Energy Prediction dataset (a single Belgian home). It is **not** validated for "
            "Indian households, and it is **not** a per-appliance forecast. Only AC and Cooler "
            "telemetry currently include the temperature+humidity readings this model needs."
        )
        pred_cols = st.columns(len(ml_predictions))
        for i, (aid, pred) in enumerate(ml_predictions.items()):
            with pred_cols[i]:
                st.markdown(f"**{APPLIANCE_LABELS.get(aid, aid)}**")
                if pred.get("model_available"):
                    st.metric(
                        "Predicted household energy",
                        f"{pred['predicted_household_energy_wh']:.1f} Wh",
                    )
                    st.caption(
                        f"±{pred['confidence_rmse']:.1f} Wh RMSE on held-out test data "
                        f"(model: {pred.get('model_version', 'n/a')})"
                    )
                else:
                    st.caption(f"⚠️ Prediction unavailable — {pred.get('error') or 'unknown reason'}. "
                               "Deterministic recommendations below are unaffected.")

    render_smart_recommendations(smart_report)

    if fridge_anomaly["status"] == "WARNING":
        st.error(f"⚠️ **Fridge anomaly detected** (score {fridge_anomaly['anomaly_score']:.0f}/100) — {fridge_anomaly['recommendation']}")
    else:
        st.success(f"✅ Fridge power draw looks normal (anomaly score {fridge_anomaly['anomaly_score']:.0f}/100).")

    dryrun_flag, avg_pump, total_water = dryrun_info
    if dryrun_flag:
        st.error(f"⚠️ **Cooler pump dry-run suspected** — avg pump duty {avg_pump:.0f}% but only "
                 f"{total_water:.3f}L drawn over the last several readings. Fan is running with little "
                 "to no water reaching the pads — check the water supply/pump.")

    washer_advice = washing_machine_schedule_advice(raw_readings["washer"].get("cycle"))
    if washer_advice:
        (st.warning if washer_advice["should_wait"] else st.info)(f"🧺 {washer_advice['message']}")

    st.divider()
    render_trend_charts()

    st.divider()
    st.subheader("🔧 Per-Appliance Recommendations")
    cols = st.columns(4)
    icons = {"ac": "❄️", "refrigerator": "🧊", "washing_machine": "🧺", "cooler": "🌀"}
    for i, rec in enumerate(household_report["recommendations"]):
        with cols[i]:
            st.markdown(f"#### {icons.get(rec['appliance'], '')} {rec['appliance'].replace('_', ' ').title()}")
            st.markdown(f"**{rec['recommendation']}**")
            st.caption(rec["reason"])
            st.caption(f"Energy: {rec['baseline_energy_kwh']:.3f} → {rec['optimized_energy_kwh']:.3f} kWh")
            if rec["baseline_water_liters"] or rec["optimized_water_liters"]:
                st.caption(f"Water: {rec['baseline_water_liters']:.2f} → {rec['optimized_water_liters']:.2f} L")

    st.divider()
    st.subheader("📡 Raw Live Readings")
    raw_cols = st.columns(4)
    labels = {"ac": "AC", "fridge": "Refrigerator", "washer": "Washing Machine", "cooler": "Desert Cooler"}
    for i, key in enumerate(["ac", "fridge", "washer", "cooler"]):
        with raw_cols[i]:
            st.markdown(f"**{labels[key]}**")
            reading = raw_readings[key]
            if reading:
                for k, v in reading.items():
                    if k not in ("id", "appliance_id", "timestamp") and v is not None:
                        st.caption(f"{k}: {v}")
            else:
                st.caption("no data yet")


# ============================================================
# TAB: LIVE DASHBOARD — auto-connects and auto-refreshes, no buttons
# ============================================================
with tab_dash:

    @st.fragment(run_every=poll_interval)
    def live_dashboard_fragment():
        alive, err = check_backend_alive(base_url)
        if not alive:
            st.error(f"❌ Backend not reachable at {base_url}: {err}\n\n"
                     "Make sure both the backend (`uvicorn app.main:app --port 8000`) and the "
                     "simulator (`python main.py`) are running.")
            return

        latest = get_all_appliances_latest(base_url=base_url, limit=1)
        outside_temp, outside_humidity, weather_source = get_outside_conditions(lat, lon)
        household_report, fridge_anomaly, raw_readings, dryrun_info = map_and_optimize(latest, outside_temp, outside_humidity)
        ml_predictions = fetch_ml_predictions(base_url)
        smart_report = build_energy_recommendations(
            raw_readings, household_report, fridge_anomaly, dryrun_info, ml_predictions
        )
        washer_advice = washing_machine_schedule_advice(raw_readings["washer"].get("cycle"))

        st.caption(f"🔴 Live — updates every {poll_interval}s")
        if is_simple:
            render_consumer_view(household_report, fridge_anomaly, raw_readings, outside_temp,
                                  weather_source, dryrun_info, washer_advice, smart_report)
        else:
            render_snapshot(household_report, fridge_anomaly, raw_readings, outside_temp, outside_humidity,
                            weather_source, dryrun_info, ml_predictions, smart_report)

    live_dashboard_fragment()

# ============================================================
# TAB: VISION DIAGNOSTICS
# ============================================================
with tab_vision:
    st.subheader("📷 Phone-Camera Appliance Health Check")
    st.write(
        "Upload a real photo — fridge interior, AC filter, or cooler pad — and the analyzer reads "
        "actual pixel statistics (brightness, saturation, texture) to flag frost, dust, or scale buildup."
    )
    st.info(
        "**Honesty note:** this is a lightweight rule-based image-statistics analyzer — genuinely "
        "analyzes whatever photo you upload, but is not a trained CNN. A production version would "
        "swap in a small fine-tuned model (e.g. MobileNet) trained on a labeled photo dataset.",
        icon="ℹ️"
    )

    check_type = st.radio("Select check type:", options=list(ANALYZERS.keys()),
                           format_func=lambda k: ANALYZERS[k][0], horizontal=True)
    uploaded = st.file_uploader("Upload a photo (JPG/PNG)", type=["jpg", "jpeg", "png"])

    if uploaded is not None:
        col_img, col_result = st.columns([1, 1])
        with col_img:
            img = Image.open(uploaded)
            st.image(img, caption="Uploaded photo", use_container_width=True)
        with col_result:
            label, analyzer_fn = ANALYZERS[check_type]
            result = analyzer_fn(uploaded)
            severity_style = {"high": ("🔴", "error"), "medium": ("🟡", "warning"), "none": ("🟢", "success")}
            icon, style = severity_style.get(result["severity"], ("⚪", "info"))
            st.markdown(f"### {icon} {result['verdict']}")
            st.metric(result["metric_name"], result["metric_value"])
            getattr(st, style)(result["action"])
    else:
        st.caption("No photo uploaded yet — try a fridge interior, an AC filter mesh, or a cooler pad photo.")
