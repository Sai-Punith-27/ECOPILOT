# EcoPilot Backend

FastAPI + SQLite backend for the EcoPilot prototype.

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

On first run this creates `ecopilot.db` in the `backend/` folder and seeds
4 appliances: `ac_01`, `fridge_01`, `washer_01`, `cooler_01`.

Interactive docs: http://localhost:8000/docs

## Endpoints

- `GET /health`
- `GET /api/appliances`
- `GET /api/appliances/{appliance_id}`
- `POST /api/telemetry`
- `GET /api/telemetry/{appliance_id}?limit=50`
