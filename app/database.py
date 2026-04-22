from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, JSON, Text, func
)
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
APP_ENV = os.getenv("APP_ENV", "local")

if APP_ENV == "production":
    connect_args = {"ssl": "require"}   
else:
    connect_args = {"ssl": None}        

# ── Engine ─────────────────────────────────────────────────────────────────────

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    connect_args=connect_args
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base ───────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Tables ─────────────────────────────────────────────────────────────────────

class EventRecord(Base):
    __tablename__ = "events"

    event_id   = Column(String, primary_key=True)
    store_id   = Column(String, nullable=False, index=True)
    camera_id  = Column(String, nullable=False)
    visitor_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    timestamp  = Column(DateTime(timezone=True), nullable=False, index=True)
    zone_id    = Column(String, nullable=True)
    dwell_ms   = Column(Integer, default=0)
    is_staff   = Column(Boolean, default=False)
    confidence = Column(Float, nullable=False)
    meta       = Column(JSON, nullable=True)
    ingested_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )


# ── Dependency ─────────────────────────────────────────────────────────────────

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Init ───────────────────────────────────────────────────────────────────────

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)