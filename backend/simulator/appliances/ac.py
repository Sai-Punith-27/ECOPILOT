"""
Simulates a Living Room AC (ac_01).

Model (kept simple on purpose, but not purely random):
- The room has a "current" temperature that drifts toward an ambient level
  when the AC isn't actively cooling, and drops when it is.
- The AC cools harder (more power) the further the room is above setpoint.
- Occupancy adds a small extra heat load and occasionally toggles, like
  someone walking in or out of the room.
"""
import random
from typing import Optional


class AirConditioner:
    appliance_id: str = "ac_01"

    def __init__(self) -> None:
        self.temperature: float = 29.0  # starts warm, like a room that's been closed up
        self.humidity: float = 60.0
        self.setpoint: float = round(random.uniform(22.0, 26.0), 1)
        self.occupancy: bool = True
        self.power_watts: float = 0.0
        self._tick_count: int = 0

    def _update_occupancy(self) -> None:
        # Every ~15 ticks (30s at 2s interval), there's a chance someone enters/leaves.
        self._tick_count += 1
        if self._tick_count % 15 == 0 and random.random() < 0.3:
            self.occupancy = not self.occupancy

    def update(self) -> None:
        """Advance the simulation by one tick (one telemetry interval)."""
        self._update_occupancy()

        diff = self.temperature - self.setpoint
        ambient_target = 32.0 if self.occupancy else 30.0  # room warms toward this if AC is idle

        if diff > 0.3:
            # Room is warmer than setpoint: AC actively cools, harder the bigger the gap.
            cooling_power = 800 + min(diff, 8) * 100
            self.power_watts = round(min(cooling_power, 1800), 1)
            self.temperature -= random.uniform(0.15, 0.35)
        else:
            # Near or below setpoint: AC idles/cycles at low power.
            self.power_watts = round(random.uniform(50, 150), 1)
            if self.temperature < ambient_target:
                self.temperature += random.uniform(0.02, 0.08)

        if self.occupancy:
            self.temperature += random.uniform(0.0, 0.03)  # small extra heat load from occupants

        self.temperature = round(max(18.0, min(self.temperature, 35.0)), 1)

        # Humidity drifts gradually toward a target instead of jumping randomly.
        humidity_target = 55.0 if self.occupancy else 50.0
        if self.power_watts > 700:
            humidity_target -= 5.0  # active cooling dehumidifies a bit
        self.humidity += (humidity_target - self.humidity) * 0.05 + random.uniform(-0.5, 0.5)
        self.humidity = round(max(30.0, min(self.humidity, 80.0)), 1)

    def to_payload(self) -> dict:
        """Only the fields relevant to an AC — matches the backend's telemetry schema."""
        return {
            "appliance_id": self.appliance_id,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "power_watts": self.power_watts,
            "occupancy": self.occupancy,
            "setpoint": self.setpoint,
        }

    def display(self) -> str:
        occ = "Occupied" if self.occupancy else "Empty"
        return (
            f"[AC]      {self.temperature:>5.1f}°C | {self.humidity:>4.1f}% RH | "
            f"{self.power_watts:>6.1f}W | {occ:<8} | SP:{self.setpoint}°C"
        )

    def refill_message(self) -> Optional[str]:
        """AC has no refill events; present so main.py can treat all appliances uniformly."""
        return None
