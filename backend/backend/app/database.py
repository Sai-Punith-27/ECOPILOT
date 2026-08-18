"""
Database setup for EcoPilot.

Uses SQLite so the whole team can run the backend with zero external
services. The .db file is created automatically the first time the
server starts (see app/main.py).
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# The SQLite file will be created in the backend/ folder (where you run uvicorn from),
# unless SQLITE_DB_PATH is set (used in Docker to point at a mounted volume so data
# survives container restarts/redeploys).
_db_path = os.environ.get("SQLITE_DB_PATH", "./ecopilot.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_db_path}"

# check_same_thread=False is required for SQLite when used with FastAPI,
# because FastAPI can access the DB from different threads.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that provides a DB session per request and closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
