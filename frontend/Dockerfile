# Build context is the EcoPilot/ repo root (see docker-compose.yml), because
# app.py imports the sibling ai-optimizers/ai package via a relative path
# (../ai-optimizers/ai) — see the sys.path setup at the top of frontend/app.py.
FROM python:3.11-slim

WORKDIR /app

COPY frontend/requirements.txt frontend/requirements.txt
RUN pip install --no-cache-dir -r frontend/requirements.txt

COPY frontend/ frontend/
COPY ai-optimizers/ ai-optimizers/

WORKDIR /app/frontend

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
