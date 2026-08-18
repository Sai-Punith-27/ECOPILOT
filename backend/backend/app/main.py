"""
EcoPilot backend entrypoint.

Run with:  uvicorn app.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models
from app.database import Base, SessionLocal, engine
from app.routes import appliances, health, prediction, telemetry

# The 4 appliances this prototype manages. Fixed for now — a future task
# could make this configurable, but the brief is explicit about these 4.
DEFAULT_APPLIANCES = [
    {"id": "ac_01", "type": "AC", "name": "Living Room AC"},
    {"id": "fridge_01", "type": "REFRIGERATOR", "name": "Kitchen Refrigerator"},
    {"id": "washer_01", "type": "WASHING_MACHINE", "name": "Washing Machine"},
    {"id": "cooler_01", "type": "DESERT_COOLER", "name": "Desert Air Cooler"},
]


def seed_appliances() -> None:
    """Insert the 4 default appliances if they don't already exist. Safe to call every startup."""
    db = SessionLocal()
    try:
        for item in DEFAULT_APPLIANCES:
            exists = db.query(models.Appliance).filter(models.Appliance.id == item["id"]).first()
            if exists is None:
                db.add(models.Appliance(**item))
        db.commit()
    finally:
        db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="EcoPilot Backend", version="0.1.0")

    # Permissive CORS for prototype stage so the (future) frontend, on any
    # localhost port, can call this API. No cookies/credentials are used,
    # so a wildcard origin is safe here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(appliances.router)
    app.include_router(telemetry.router)
    app.include_router(prediction.router)

    @app.on_event("startup")
    def on_startup():
        Base.metadata.create_all(bind=engine)  # creates ecopilot.db + tables if missing
        seed_appliances()

    return app


app = create_app()
