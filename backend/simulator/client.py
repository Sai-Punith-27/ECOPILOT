"""
Handles all HTTP communication with the FastAPI backend.

Kept separate from the appliance simulation logic so the appliances
don't need to know anything about requests, timeouts, or retries.
"""
from typing import Optional

import requests

from config import REQUEST_TIMEOUT_SECONDS, TELEMETRY_URL


class TelemetryClient:
    """Sends telemetry payloads to the backend and tracks connection health."""

    def __init__(self, url: str = TELEMETRY_URL, timeout: float = REQUEST_TIMEOUT_SECONDS) -> None:
        self.url = url
        self.timeout = timeout
        self._backend_was_down = False  # tracks state so we don't spam the same message

    def send(self, payload: dict) -> Optional[int]:
        """
        Send one telemetry reading to the backend.

        Returns:
            The HTTP status code (e.g. 201, 404, 422) if the request reached
            the server, or None if the backend could not be reached at all
            (connection refused, timeout, DNS failure, etc.).
        """
        try:
            response = requests.post(self.url, json=payload, timeout=self.timeout)

            if self._backend_was_down:
                print("[OK] Backend connection restored.")
                self._backend_was_down = False

            return response.status_code

        except requests.exceptions.RequestException:
            if not self._backend_was_down:
                print("[ERROR] Backend unavailable. Retrying...")
                self._backend_was_down = True
            return None
