# Build context is the EcoPilot/ repo root (see docker-compose.yml), NOT
# backend/backend/, because app/ml_bridge.py imports the sibling
# ai-optimizers/ml package (../../../ai-optimizers/ml relative to this
# service) to run the trained energy-prediction model. Mirrors the same
# pattern already used by frontend/Dockerfile for ai-optimizers/ai.
FROM python:3.11-slim

WORKDIR /app

COPY backend/backend/requirements.txt backend/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/backend/requirements.txt

COPY backend/backend/ backend/backend/
COPY ai-optimizers/ ai-optimizers/

WORKDIR /app/backend/backend

# SQLite file will live in this volume-mounted directory (see docker-compose.yml)
VOLUME ["/app/backend/backend/data"]
ENV SQLITE_DB_PATH=/app/backend/backend/data/ecopilot.db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
