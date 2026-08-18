"""
Configuration for the EcoPilot IoT simulator.

Keeping these values in one place means you only need to change them
here if the backend URL, timing, or timeout needs to change.
"""

import os

# The existing FastAPI backend from Task 1. Not modified by this simulator.
# Reads from BACKEND_BASE_URL env var if set (e.g. your deployed Render URL),
# falling back to localhost for local development.
BACKEND_BASE_URL: str = os.environ.get("BACKEND_BASE_URL", "http://127.0.0.1:8000")
TELEMETRY_URL: str = f"{BACKEND_BASE_URL}/api/telemetry"

# How often (in seconds) each appliance sends a new telemetry reading.
SEND_INTERVAL_SECONDS: float = 2.0

# How long (in seconds) to wait for the backend to respond before treating
# the request as failed. Keeps the simulator from freezing if the backend
# hangs.
REQUEST_TIMEOUT_SECONDS: float = 3.0

