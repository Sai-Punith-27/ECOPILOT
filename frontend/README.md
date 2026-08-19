# EcoPilot Frontend — Live Dashboard

A Streamlit dashboard that pulls **live telemetry** from the real EcoPilot
backend and runs it through the team's actual AI optimizer modules
(`ai-optimizers/ai/`) to produce real-time recommendations: optimal AC
setpoint, cooler fan/pump setting, washing-machine mode, fridge anomaly
detection, and household-level energy/water/cost/carbon savings with a
resource efficiency score.

This is **not a simulation of a UI** — every number you see is computed
from a real HTTP call to a real running backend, fed by a real (simulated
appliance) IoT client, passed through the team's actual optimizer logic.

## Prerequisites — 2 other processes must be running first

**Terminal 1 — the backend:**
```bash
cd ../backend/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — the simulator (feeds live data into the backend):**
```bash
cd ../backend/simulator
pip install -r requirements.txt
python main.py
```
Leave both running. You should see `[OK] Telemetry sent successfully` printing
every ~15 seconds in Terminal 2.

## Run the frontend

**Terminal 3:**
```bash
cd frontend
pip install -r requirements.txt
streamlit run app.py
```

In the sidebar: check the backend connection, then click **Start Live
Monitoring**. The dashboard will refresh automatically for the number of
cycles you set, showing live readings and live recommendations.

## Sharing a live link (e.g. for your mentor to view remotely)

Once the dashboard is running (`streamlit run app.py`), open a 4th terminal:
```bash
npx untun tunnel http://localhost:8501
```
This gives a public URL (e.g. `https://random-words.trycloudflare.com`) in
seconds — free, no signup. Your laptop must stay on and connected for as
long as anyone is viewing it; it's a live tunnel, not a permanent hosted
deployment. The dashboard's backend calls (`localhost:8000`) still work
fine since they happen server-side on your own machine.

## Honest documentation — what's real vs. what's an assumption

The telemetry schema (see `../backend/backend/app/schemas.py`) reports
what each appliance itself knows — its own temperature, power draw, fan
speed, etc. It does **not** include a few fields the optimizer modules
need but that no appliance can self-report:

| Field | Source in this dashboard |
|---|---|
| `outside_temperature` / `ambient_temperature` | **Real** live call to Open-Meteo (free, no API key) for the location you set in the sidebar. Falls back to a fixed 33°C default only if the weather API is unreachable. |
| `dirt_level`, `water_hardness`, `deadline_minutes` (washing machine) | These are decisions a **person** makes when starting a wash cycle, not sensor data — exposed as sidebar inputs with sensible defaults, not fabricated as if a sensor reported them. |
| `historical_average_power`, `door_open_count` (fridge anomaly) | Computed live from the readings collected **during the current monitoring session** — starts fresh each time you click "Start Live Monitoring." |
| `occupancy` for the cooler | The telemetry schema only has an `occupancy` field for the AC. The cooler's occupancy is assumed to match the AC's (same household, same time) — documented here rather than silently guessed. |

Everything else — temperature, power, water level, fan speed, pump duty,
door state — comes directly from the live backend, unmodified.

## Features

- **Live optimizer recommendations** — AC/fridge/washer/cooler settings via the team's real AI optimizer modules
- **Household summary** — energy/water/cost/carbon savings + resource score
- **Fridge anomaly detection** — flags abnormal power draw vs. session history
- **Cooler pump dry-run detection** — flags fan running with ~0 water drawn over recent readings (rule-based, direct on real telemetry)
- **Live trend charts** — power/water per appliance over the monitoring session
- **Time-of-day tariff scheduling** — advises waiting for off-peak hours for the washing machine (illustrative tariff schedule, not a live DISCOM feed — see `tariff.py`)
- **Vision diagnostics tab** — photo-based frost/dirty-filter/dry-pad checks (rule-based image statistics, not a trained CNN — see in-app note)

## Files

- `app.py` — the dashboard itself
- `backend_client.py` — HTTP client for the EcoPilot backend's `/api/telemetry` endpoints
- `weather_client.py` — Open-Meteo client for outside temperature/humidity
- `tariff.py` — illustrative time-of-day tariff schedule + washing-machine scheduling advice
- `vision_diagnostics.py` — photo-based frost/dirt/scale analyzers
- `requirements.txt` — `streamlit`, `requests`, `plotly`, `Pillow`
