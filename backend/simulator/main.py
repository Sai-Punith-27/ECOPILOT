"""
EcoPilot IoT Simulator — orchestrator.

Runs all 4 appliance simulators, sending HTTP telemetry to the existing
FastAPI backend every SEND_INTERVAL_SECONDS, until stopped with Ctrl+C.

Run from inside the simulator/ folder:
    python main.py
"""
import time
from datetime import datetime, timezone

from client import TelemetryClient
from config import SEND_INTERVAL_SECONDS

from appliances.ac import AirConditioner
from appliances.desert_cooler import DesertCooler
from appliances.refrigerator import Refrigerator
from appliances.washing_machine import WashingMachine


def print_header() -> None:
    print("=" * 60)
    print("ECOPILOT IoT SIMULATOR")
    print("=" * 60)
    print(f"Sending simulated telemetry every {SEND_INTERVAL_SECONDS:.0f}s. Press Ctrl+C to stop.\n")


def run() -> None:
    client = TelemetryClient()

    ac = AirConditioner()
    fridge = Refrigerator()
    washer = WashingMachine()
    cooler = DesertCooler()

    appliances = [ac, fridge, washer, cooler]

    print_header()

    try:
        while True:
            # 1. Advance each appliance's simulated state by one tick.
            for appliance in appliances:
                appliance.update()

            # 2. Report any refill events before the readings, so they stand out.
            for appliance in appliances:
                message = appliance.refill_message()
                if message:
                    print(message)

            # 3. Print a human-readable line per appliance.
            print(ac.display())
            print(fridge.display())
            print(washer.display())
            print(cooler.display())

            # 4. Send each appliance's telemetry to the backend.
            all_ok = True
            for appliance in appliances:
                payload = appliance.to_payload()
                payload["timestamp"] = datetime.now(timezone.utc).isoformat()

                status_code = client.send(payload)

                if status_code is None:
                    all_ok = False  # backend unreachable; client.py already printed the error
                elif status_code >= 400:
                    all_ok = False
                    print(f"[HTTP {status_code}] Failed to store telemetry for {appliance.appliance_id}")

            if all_ok:
                print("[OK] Telemetry sent successfully (HTTP 201 x4)")

            print("-" * 60)
            time.sleep(SEND_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nSimulator stopped by user. Goodbye!")


if __name__ == "__main__":
    run()
