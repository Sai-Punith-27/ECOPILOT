"""Endpoints for submitting and reading appliance telemetry."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@router.post("", response_model=schemas.TelemetryOut, status_code=201)
def create_telemetry(payload: schemas.TelemetryCreate, db: Session = Depends(get_db)):
    """
    Store one telemetry reading for an appliance.
    Rejects the reading (404) if the appliance_id is unknown, so we never
    silently accept data for an appliance that doesn't exist.
    """
    appliance = db.query(models.Appliance).filter(models.Appliance.id == payload.appliance_id).first()
    if appliance is None:
        raise HTTPException(status_code=404, detail=f"Appliance '{payload.appliance_id}' not found")

    data = payload.model_dump()
    if data.get("timestamp") is None:
        data["timestamp"] = datetime.utcnow()

    record = models.Telemetry(**data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/{appliance_id}", response_model=list[schemas.TelemetryOut])
def get_telemetry(
    appliance_id: str,
    limit: int = Query(default=50, ge=1, le=500, description="Max number of readings to return"),
    db: Session = Depends(get_db),
):
    """Return the most recent telemetry readings for one appliance, newest first."""
    appliance = db.query(models.Appliance).filter(models.Appliance.id == appliance_id).first()
    if appliance is None:
        raise HTTPException(status_code=404, detail=f"Appliance '{appliance_id}' not found")

    records = (
        db.query(models.Telemetry)
        .filter(models.Telemetry.appliance_id == appliance_id)
        .order_by(models.Telemetry.timestamp.desc())
        .limit(limit)
        .all()
    )
    return records
