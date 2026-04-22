from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
import structlog

from app.database import get_db, EventRecord
from app.models import HeatmapResponse, HeatmapZone

router = APIRouter()
log = structlog.get_logger()

MIN_SESSIONS_FOR_CONFIDENCE = 20


@router.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
async def get_heatmap(store_id: str, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)

    # Get visit count + avg dwell per zone
    zone_q = await db.execute(
        select(
            EventRecord.zone_id,
            func.count(EventRecord.event_id).label("visit_count"),
            func.avg(EventRecord.dwell_ms).label("avg_dwell"),
        )
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.is_staff == False)
        .where(EventRecord.zone_id != None)
        .where(EventRecord.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"]))
        .group_by(EventRecord.zone_id)
    )
    rows = zone_q.fetchall()

    if not rows:
        return HeatmapResponse(store_id=store_id, zones=[], as_of=now)

    # Normalise visit frequency 0-100
    counts = [r.visit_count for r in rows]
    max_count = max(counts) or 1

    zones = []
    for row in rows:
        normalised = round((row.visit_count / max_count) * 100, 1)
        zones.append(HeatmapZone(
            zone_id=row.zone_id,
            visit_frequency=normalised,
            avg_dwell_ms=float(row.avg_dwell or 0.0),
            data_confidence=row.visit_count >= MIN_SESSIONS_FOR_CONFIDENCE,
        ))

    # Sort by frequency descending
    zones.sort(key=lambda z: z.visit_frequency, reverse=True)

    log.info("heatmap.served", store_id=store_id, zones=len(zones))

    return HeatmapResponse(store_id=store_id, zones=zones, as_of=now)