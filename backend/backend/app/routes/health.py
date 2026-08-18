"""Simple health check so the frontend / simulator can confirm the API is up."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "ecopilot-backend"}
