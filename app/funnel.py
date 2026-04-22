from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from datetime import datetime, timezone
import structlog
from app.database import get_db, EventRecord
from app.models import FunnelResponse, FunnelStage

router = APIRouter()
log = structlog.get_logger()

@router.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
async def get_funnel(store_id: str, db: AsyncSession = Depends(get_db)):

    # Stage 1 — Total unique customer visitors (ENTRY or any zone event)
    entry_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type.in_(["ENTRY", "ZONE_ENTER", "ZONE_DWELL"]))
        .where(EventRecord.is_staff == False)
    )
    total_entries = entry_q.scalar_one_or_none() or 0

    # Stage 2 — Visitors who entered any named zone
    zone_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "ZONE_ENTER")
        .where(EventRecord.is_staff == False)
    )
    zone_visitors = zone_q.scalar_one_or_none() or 0

    # Stage 3 — Visitors who reached billing queue
    billing_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "BILLING_QUEUE_JOIN")
        .where(EventRecord.is_staff == False)
    )
    billing_visitors = billing_q.scalar_one_or_none() or 0

    # Stage 4 — Purchased = billing visitors who did NOT abandon
    abandon_q = await db.execute(
        select(distinct(EventRecord.visitor_id))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "BILLING_QUEUE_ABANDON")
        .where(EventRecord.is_staff == False)
    )
    abandoned_ids = {row[0] for row in abandon_q.fetchall()}

    billing_all_q = await db.execute(
        select(distinct(EventRecord.visitor_id))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "BILLING_QUEUE_JOIN")
        .where(EventRecord.is_staff == False)
    )
    billing_ids = {row[0] for row in billing_all_q.fetchall()}
    purchased = len(billing_ids - abandoned_ids)

    # ── Build funnel stages with drop-off % (clamped to >= 0) ────────────────
    def dropoff(current: int, previous: int) -> float:
        if previous == 0:
            return 0.0
        return max(0.0, round((1 - current / previous) * 100, 2))

    stages = [
        FunnelStage(stage="Entry",         count=total_entries,   dropoff_pct=0.0),
        FunnelStage(stage="Zone Visit",    count=zone_visitors,   dropoff_pct=dropoff(zone_visitors, total_entries)),
        FunnelStage(stage="Billing Queue", count=billing_visitors, dropoff_pct=dropoff(billing_visitors, zone_visitors)),
        FunnelStage(stage="Purchase",      count=purchased,        dropoff_pct=dropoff(purchased, billing_visitors)),
    ]

    log.info("funnel.served", store_id=store_id, entries=total_entries, purchased=purchased)

    return FunnelResponse(
        store_id=store_id,
        stages=stages,
        as_of=datetime.now(timezone.utc),
    )