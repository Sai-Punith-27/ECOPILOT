"""
Simulates the Washing Machine (washer_01).

Model:
- A simple state machine cycles through:
  IDLE -> FILLING -> WASHING -> RINSING -> SPINNING -> COMPLETE -> IDLE
- Each stage lasts a fixed number of ticks and has its own realistic
  power/water behavior (e.g. SPINNING draws the most power, IDLE draws ~0).
- A new load_kg is picked when a cycle starts and stays constant for that cycle.
"""
import random
from typing import Optional


class WashingMachine:
    appliance_id: str = "washer_01"

    # How many ticks (each tick = one SEND_INTERVAL_SECONDS) each stage lasts.
    # Kept short so you can actually see a full cycle during a demo.
    CYCLE_DURATIONS: dict[str, int] = {
        "IDLE": 10,
        "FILLING": 5,
        "WASHING": 10,
        "RINSING": 6,
        "SPINNING": 5,
        "COMPLETE": 3,
    }

    def __init__(self) -> None:
        self.cycle: str = "IDLE"
        self.load_kg: float = 0.0
        self.water_liters: float = 0.0
        self.power_watts: float = 0.0
        self._ticks_in_stage: int = 0

    def _start_new_load(self) -> None:
        self.load_kg = round(random.uniform(2.0, 6.0), 1)
        self.water_liters = 0.0

    def _transition(self, next_cycle: str) -> None:
        self.cycle = next_cycle
        self._ticks_in_stage = 0

    def update(self) -> None:
        self._ticks_in_stage += 1
        duration = self.CYCLE_DURATIONS[self.cycle]

        if self.cycle == "IDLE":
            self.power_watts = 0.0
            self.water_liters = 0.0
            if self._ticks_in_stage >= duration:
                self._start_new_load()
                self._transition("FILLING")

        elif self.cycle == "FILLING":
            self.power_watts = round(random.uniform(80, 120), 1)
            self.water_liters = round(min(self.water_liters + random.uniform(3, 5), 20.0), 1)
            if self._ticks_in_stage >= duration:
                self._transition("WASHING")

        elif self.cycle == "WASHING":
            self.power_watts = round(random.uniform(700, 900), 1)
            self.water_liters = round(max(self.water_liters + random.uniform(-0.2, 0.2), 0.0), 1)
            if self._ticks_in_stage >= duration:
                self._transition("RINSING")

        elif self.cycle == "RINSING":
            self.power_watts = round(random.uniform(300, 450), 1)
            self.water_liters = round(max(self.water_liters - random.uniform(1.5, 2.5), 0.0), 1)
            if self._ticks_in_stage >= duration:
                self._transition("SPINNING")

        elif self.cycle == "SPINNING":
            self.power_watts = round(random.uniform(1000, 1300), 1)
            self.water_liters = round(max(self.water_liters - random.uniform(1.0, 2.0), 0.0), 1)
            if self._ticks_in_stage >= duration:
                self._transition("COMPLETE")

        elif self.cycle == "COMPLETE":
            self.power_watts = round(random.uniform(0, 10), 1)
            if self._ticks_in_stage >= duration:
                self._transition("IDLE")

    def to_payload(self) -> dict:
        return {
            "appliance_id": self.appliance_id,
            "load_kg": self.load_kg,
            "water_liters": self.water_liters,
            "power_watts": self.power_watts,
            "cycle": self.cycle,
        }

    def display(self) -> str:
        return (
            f"[WASHER]  {self.load_kg:>4.1f}kg | {self.cycle:<9} | "
            f"{self.power_watts:>6.1f}W | Water:{self.water_liters:>4.1f}L"
        )

    def refill_message(self) -> Optional[str]:
        return None
