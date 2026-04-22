from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone, timedelta
import os
import structlog

from app.database import get_db, EventRecord
from app.models import HealthResponse, StoreFeedStatus

router = APIRouter()
log = structlog.get_logger()

STALE_THRESHOLD = int(os.getenv("STALE_FEED_THRESHOLD_MINUTES", 10))


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)

    try:
        # Get last event timestamp per store
        store_q = await db.execute(
            select(
                EventRecord.store_id,
                func.max(EventRecord.timestamp).label("last_event_at")
            )
            .group_by(EventRecord.store_id)
        )
        rows = store_q.fetchall()

        store_feeds = []
        any_stale = False

        for row in rows:
            last_event_at = row.last_event_at
            if last_event_at and last_event_at.tzinfo is None:
                last_event_at = last_event_at.replace(tzinfo=timezone.utc)

            minutes_since = (
                (now - last_event_at).total_seconds() / 60
                if last_event_at else None
            )
            stale = minutes_since is None or minutes_since > STALE_THRESHOLD

            if stale:
                any_stale = True

            store_feeds.append(StoreFeedStatus(
                store_id=row.store_id,
                last_event_at=last_event_at,
                stale=stale,
                minutes_since_last=round(minutes_since, 1) if minutes_since else None,
            ))

        status = "degraded" if any_stale else "ok"

        log.info("health.checked", status=status, store_count=len(store_feeds))

        return HealthResponse(
            status=status,
            store_feeds=store_feeds,
            checked_at=now,
        )

    except Exception as e:
        log.error("health.db_error", error=str(e))
        return HealthResponse(
            status="degraded",
            store_feeds=[],
            checked_at=now,
        )