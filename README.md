# EcoPilot — AI-Powered Household Resource Optimization (SIH 2026)

EcoPilot monitors and optimizes four household appliances — Air Conditioner,
Refrigerator, Washing Machine, and Desert Air Cooler — recommending actions
that reduce energy, water, cost, and carbon footprint while respecting
comfort, performance, and safety constraints.

## Architecture

```
IoT/Simulator (backend/simulator)
        │  POST /api/telemetry every ~15s
        ▼
FastAPI backend (backend/backend) ── SQLite
        │
        │  GET /api/predict/{appliance_id}  ◄── ML energy prediction
        │       (ai-optimizers/ml — scikit-learn, loaded read-only)
        │
        ▼
Streamlit frontend (frontend/app.py)
        │  1. fetches latest telemetry
        │  2. fetches ML prediction from the backend (new)
        │  3. runs the deterministic optimizers (ai-optimizers/ai, unchanged)
        │  4. renders both, side by side
        ▼
   Live Dashboard (one URL, see DEPLOY.md)
```

**What's deterministic vs. ML:**
- **Deterministic, rule-based optimization** (`ai-optimizers/ai/`) decides
  every actual recommendation — AC setpoint, cooler fan/pump duty, washing
  cycle, fridge anomaly status. This is unchanged from before ML was added,
  and remains the system of record for "what should the appliance do."
- **ML prediction** (`ai-optimizers/ml/`) adds a *new, additive* signal:
  an estimated near-term whole-household energy figure (Wh), shown
  alongside the deterministic recommendations for context/trend — it does
  **not** decide or override any recommendation.
- **If the ML model is unavailable for any reason** (not trained, backend
  can't load it, missing telemetry), the dashboard falls back to
  deterministic-only behaviour automatically — nothing else breaks.

## Where ML is used, and what makes it different (SIH explanation)

Most rule-based energy dashboards stop at "if X then do Y." EcoPilot adds a
genuinely trained ML layer **on top of, not instead of**, a transparent
rule-based optimizer — giving judges both explainability (every
recommendation traces to a stated rule) and a real predictive-analytics
component (a regression model trained on public smart-home energy data,
evaluated against a naive baseline, with reported RMSE/R²).

Specifically:
- **Dataset:** UCI "Appliances Energy Prediction" (Candanedo et al.),
  19,735 rows from a real instrumented home, Jan–May 2016.
- **Target:** whole-household appliance energy (Wh) — the dataset has no
  per-appliance breakdown, so we do **not** claim per-appliance ML
  accuracy; the dashboard says so explicitly.
- **Features used:** only ones EcoPilot's own telemetry/weather client can
  realistically supply — indoor temperature/humidity (from AC/Cooler
  sensors), outdoor temperature/humidity (live weather API), time-of-day,
  and a legitimate autoregressive feature (most recent known power
  reading). See `ai-optimizers/ml/model.py` for the full, documented
  rationale, including a feature set we tried and rejected because it
  barely beat a naive baseline (kept in `metrics.json` for transparency).
- **Result:** test RMSE 62.2 Wh vs. a naive (mean-prediction) baseline of
  90.9 Wh — R² = 0.53 on a chronological (not random) held-out split.
  Modest but genuine and honestly reported, not inflated.
- **Not claimed:** accuracy for Indian households (the training data is a
  single Belgian home) — surfaced explicitly in the API response
  (`scope_note`) and the dashboard caption, not buried in a docstring.

## Repository layout

```
backend/backend/     FastAPI + SQLite backend, port 8000
backend/simulator/    Telemetry simulator for all 4 appliances
frontend/              Streamlit dashboard, port 8501
ai-optimizers/ai/       Deterministic, rule-based optimizers (unchanged)
ai-optimizers/ml/        ML energy-prediction pipeline (new)
DEPLOY.md                 Full deployment instructions (Streamlit Cloud +
                           Render, or Docker on your own VPS)
```

## Run locally (3 terminals — unchanged from before)

**Backend:**
```bash
cd backend/backend
venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

**Simulator:**
```bash
cd backend/simulator
venv\Scripts\activate
python main.py
```

**Frontend:**
```bash
cd frontend
venv\Scripts\activate
streamlit run app.py
```

Open `http://localhost:8501`.

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for full step-by-step instructions — both the
recommended one-URL path (Streamlit Community Cloud + Render, no server to
manage) and a Docker/VPS alternative.

## Testing

```bash
# Deterministic optimizers (132 tests, unchanged)
cd ai-optimizers/ai && python -m pytest tests/ test_optimizer.py -q

# ML pipeline (9 tests)
cd ai-optimizers/ml && python -m pytest tests/test_inference.py -v
```

Manual end-to-end verification performed during development: backend health
checks, telemetry POST/GET, `/api/predict/{id}` for all 4 appliances
(normal, no-data, and unknown-appliance cases), a live simulator run against
the backend, and a full Streamlit script execution (via `AppTest`) confirming
the ML section renders correctly with zero unhandled exceptions.

## Honesty notes (read before demoing)

- All energy/water/cost/carbon figures from the deterministic optimizers are
  **simulated**, based on documented assumptions (see
  `ai-optimizers/ai/README.md`) — not measured hardware data.
- The ML model's predictions are a genuine trained estimate, but trained on
  a different country's single household and only reach moderate accuracy
  (R²=0.53) — presented as an indicative trend, not ground truth.
- The time-of-day electricity tariff shown is illustrative (typical shape of
  Indian state ToD orders), not a live DISCOM feed.
