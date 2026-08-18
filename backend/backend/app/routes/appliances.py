"""Endpoints for reading appliance information."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/appliances", tags=["appliances"])


@router.get("", response_model=list[schemas.ApplianceOut])
def list_appliances(db: Session = Depends(get_db)):
    """Return all known appliances (the 4 seeded on startup)."""
    return db.query(models.Appliance).all()


@router.get("/{appliance_id}", response_model=schemas.ApplianceOut)
def get_appliance(appliance_id: str, db: Session = Depends(get_db)):
    """Return one appliance by id, or 404 if it doesn't exist."""
    appliance = db.query(models.Appliance).filter(models.Appliance.id == appliance_id).first()
    if appliance is None:
        raise HTTPException(status_code=404, detail=f"Appliance '{appliance_id}' not found")
    return appliance
