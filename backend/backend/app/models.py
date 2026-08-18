"""
SQLAlchemy models — these define the actual database tables.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Appliance(Base):
    """A physical appliance we monitor. Rows are seeded on startup."""

    __tablename__ = "appliances"

    id = Column(String, primary_key=True, index=True)  # e.g. "ac_01"
    type = Column(String, nullable=False)  # e.g. "AC"
    name = Column(String, nullable=False)  # e.g. "Living Room AC"

    telemetry_records = relationship("Telemetry", back_populates="appliance")


class Telemetry(Base):
    """
    One sensor reading from one appliance at one point in time.

    Most fields are nullable because different appliances report different
    sensors (e.g. only the washer sends load_kg, only the fridge sends door_open).
    """

    __tablename__ = "telemetry"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    appliance_id = Column(String, ForeignKey("appliances.id"), nullable=False, index=True)

    temperature = Column(Float, nullable=True)   # degrees Celsius
    humidity = Column(Float, nullable=True)       # percent, 0-100
    power_watts = Column(Float, nullable=True)    # watts
    water_liters = Column(Float, nullable=True)   # liters used

    occupancy = Column(Boolean, nullable=True)    # room occupied (AC)
    door_open = Column(Boolean, nullable=True)    # fridge door open

    water_level = Column(Float, nullable=True)    # tank level percent (cooler)
    load_kg = Column(Float, nullable=True)        # laundry load weight (washer)
    fan_speed = Column(Integer, nullable=True)    # fan speed level (AC/cooler)
    pump_duty = Column(Float, nullable=True)      # water pump duty cycle percent (cooler)
    setpoint = Column(Float, nullable=True)        # target temperature/setting
    cycle = Column(String, nullable=True)          # e.g. "wash", "cooling", "idle"

    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    appliance = relationship("Appliance", back_populates="telemetry_records")
