"""
Simulates the Desert Air Cooler (cooler_01).

Model:
- There's an internal comfort target the cooler tries to reach (not sent
  to the backend, since the telemetry schema has no cooler setpoint field).
- When the room is warmer than the target, fan and pump ramp up.
- Active pump use cools the room, raises humidity (evaporative cooling),
  and consumes water from the tank.
- When the tank gets low, it auto-refills (simulating someone topping it
  up or an auto-fill valve) and a refill event is reported.

Note on fan_speed: the backend's telemetry schema constrains fan_speed to
an integer level 0-5 (not a percentage), so we simulate it as a level and
convert to a percentage only for the terminal display.
"""
import random
from typing import Optional


class DesertCooler:
    appliance_id: str = "cooler_01"

    COMFORT_TARGET: float = 26.0
    LOW_WATER_THRESHOLD: float = 15.0
    MAX_FAN_SPEED: int = 5

    def __init__(self) -> None:
        self.temperature: float = 34.0
        self.humidity: float = 35.0
        self.water_level: float = 80.0
        self.fan_speed: int = 3
        self.pump_duty: float = 40.0
        self.power_watts: float = 0.0
        self.water_liters: float = 0.0  # water consumed in this tick
        self._refill_happened: bool = False

    def update(self) -> None:
        self._refill_happened = False
        diff = self.temperature - self.COMFORT_TARGET

        if diff > 0.5:
            # Too warm: ramp fan and pump up.
            if random.random() < 0.3:
                self.fan_speed = min(self.MAX_FAN_SPEED, self.fan_speed + 1)
            self.fan_speed = max(2, self.fan_speed)
            self.pump_duty = min(100.0, self.pump_duty + random.uniform(2, 6))
        else:
            # Close to/at target: ease off.
            if random.random() < 0.3:
                self.fan_speed = max(1, self.fan_speed - 1)
            self.pump_duty = max(10.0, self.pump_duty - random.uniform(2, 6))

        self.pump_duty = round(max(0.0, min(self.pump_duty, 100.0)), 1)

        if self.pump_duty > 15:
            # Evaporative cooling: pump activity cools the room and raises humidity.
            cooling = 0.1 + (self.pump_duty / 100) * 0.3
            self.temperature -= cooling
            self.humidity += (self.pump_duty / 100) * random.uniform(0.3, 0.8)

            consumed = round((self.pump_duty / 100) * random.uniform(0.15, 0.35), 2)
            self.water_level -= consumed
            self.water_liters = consumed
        else:
            # Pump mostly idle: room drifts warmer, humidity settles back down.
            self.temperature += random.uniform(0.05, 0.15)
            self.humidity -= random.uniform(0.1, 0.3)
            self.water_liters = 0.0

        # Fan alone contributes a small amount of circulation cooling.
        self.temperature -= (self.fan_speed / self.MAX_FAN_SPEED) * 0.02

        self.temperature = round(max(20.0, min(self.temperature, 40.0)), 1)
        self.humidity = round(max(20.0, min(self.humidity, 90.0)), 1)

        if self.water_level <= self.LOW_WATER_THRESHOLD:
            self.water_level = 100.0
            self._refill_happened = True

        self.water_level = round(max(0.0, min(self.water_level, 100.0)), 1)

        fan_power = (self.fan_speed / self.MAX_FAN_SPEED) * 60
        pump_power = (self.pump_duty / 100) * 90
        self.power_watts = round(fan_power + pump_power + random.uniform(0, 5), 1)

    def to_payload(self) -> dict:
        return {
            "appliance_id": self.appliance_id,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "water_level": self.water_level,
            "fan_speed": self.fan_speed,
            "pump_duty": self.pump_duty,
            "power_watts": self.power_watts,
            "water_liters": self.water_liters,
        }

    def display(self) -> str:
        fan_percent = int((self.fan_speed / self.MAX_FAN_SPEED) * 100)
        return (
            f"[COOLER]  {self.temperature:>5.1f}°C | {self.humidity:>4.1f}% RH | "
            f"Water:{self.water_level:>5.1f}% | Fan:{fan_percent:>3}% | "
            f"Pump:{self.pump_duty:>4.1f}% | {self.power_watts:>6.1f}W"
        )

    def refill_message(self) -> Optional[str]:
        if self._refill_happened:
            return "[REFILL] cooler_01 water tank refilled to 100%"
        return None
