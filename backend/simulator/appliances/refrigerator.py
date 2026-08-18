"""
Simulates the Kitchen Refrigerator (fridge_01).

Model:
- Temperature normally sits around 4-5°C.
- Opening the door lets warm air in, so temperature rises while it's open.
- Once closed, the compressor works to bring the temperature back down,
  drawing more power while actively cooling, and very little once it
  reaches target and cycles off.
"""
import random
from typing import Optional


class Refrigerator:
    appliance_id: str = "fridge_01"

    TARGET_TEMPERATURE: float = 5.0

    def __init__(self) -> None:
        self.temperature: float = 4.5
        self.door_open: bool = False
        self.power_watts: float = 120.0
        self._door_open_ticks_remaining: int = 0

    def _update_door(self) -> None:
        if self.door_open:
            self._door_open_ticks_remaining -= 1
            if self._door_open_ticks_remaining <= 0:
                self.door_open = False
        else:
            # Small chance each tick (~2s) that someone opens the door.
            if random.random() < 0.05:
                self.door_open = True
                self._door_open_ticks_remaining = random.randint(2, 5)  # stays open 4-10s

    def update(self) -> None:
        self._update_door()

        if self.door_open:
            self.temperature += random.uniform(0.3, 0.8)
            self.power_watts = round(random.uniform(150, 200), 1)  # light on + compressor working harder
        else:
            if self.temperature > self.TARGET_TEMPERATURE:
                self.temperature -= random.uniform(0.2, 0.5)
                self.power_watts = round(random.uniform(110, 160), 1)  # actively cooling
            else:
                self.power_watts = round(random.uniform(5, 40), 1)  # compressor cycled off

        self.temperature = round(max(1.0, min(self.temperature, 15.0)), 1)

    def to_payload(self) -> dict:
        return {
            "appliance_id": self.appliance_id,
            "temperature": self.temperature,
            "power_watts": self.power_watts,
            "door_open": self.door_open,
        }

    def display(self) -> str:
        door = "Door Open" if self.door_open else "Door Closed"
        return f"[FRIDGE]  {self.temperature:>5.1f}°C | {door:<11} | {self.power_watts:>6.1f}W"

    def refill_message(self) -> Optional[str]:
        return None
