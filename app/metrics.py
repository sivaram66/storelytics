import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
import structlog

from app.database import get_db, EventRecord
from app.models import MetricsResponse, ZoneDwell

router = APIRouter()
log = structlog.get_logger()


POS_FILE   = Path("data/pos_transactions.csv")
POS_WINDOW = timedelta(minutes=5)


def load_pos_transactions(store_id: str) -> list[datetime]:
    """Load POS transaction timestamps for a given store from CSV."""
    if not POS_FILE.exists():
        return []
    timestamps = []
    with open(POS_FILE, newline="") as f:
        for row in csv.DictReader(f):
            if row["store_id"] == store_id:
                ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                timestamps.append(ts)
    return timestamps


@router.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
async def get_metrics(store_id: str, db: AsyncSession = Depends(get_db)):

    # ── Unique customer visitors (exclude staff) ───────────────────────────────
    unique_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type.in_(["ENTRY", "ZONE_ENTER", "ZONE_DWELL"]))
        .where(EventRecord.is_staff == False)
    )
    unique_visitors = unique_q.scalar_one_or_none() or 0

    # ── Conversion: POS-correlated (5-min billing window) ─────────────────────
    pos_timestamps = load_pos_transactions(store_id)

    if pos_timestamps:
        # Fetch all non-staff billing zone visits with timestamps
        billing_visits_q = await db.execute(
            select(EventRecord.visitor_id, EventRecord.timestamp)
            .where(EventRecord.store_id == store_id)
            .where(EventRecord.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"]))
            .where(EventRecord.zone_id.ilike("%billing%"))
            .where(EventRecord.is_staff == False)
        )
        billing_visits = billing_visits_q.fetchall()

        converted = set()
        for visitor_id, visit_ts in billing_visits:
            if visit_ts.tzinfo is None:
                visit_ts = visit_ts.replace(tzinfo=timezone.utc)
            for tx_ts in pos_timestamps:
                # Visitor was in billing zone within 5 minutes before transaction
                if timedelta(0) <= (tx_ts - visit_ts) <= POS_WINDOW:
                    converted.add(visitor_id)
                    break

        billing_visitors = len(converted)
    else:
        # Fallback: count non-staff visitors who reached billing zone
        billing_q = await db.execute(
            select(func.count(distinct(EventRecord.visitor_id)))
            .where(EventRecord.store_id == store_id)
            .where(EventRecord.event_type.in_(["BILLING_QUEUE_JOIN", "ZONE_ENTER"]))
            .where(EventRecord.zone_id.ilike("%billing%"))
            .where(EventRecord.is_staff == False)
        )
        billing_visitors = billing_q.scalar_one_or_none() or 0

    conversion_rate = round(billing_visitors / unique_visitors, 4) if unique_visitors > 0 else 0.0

    # ── Average dwell across all zones (customers only) ───────────────────────
    dwell_q = await db.execute(
        select(func.avg(EventRecord.dwell_ms))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.is_staff == False)
        .where(EventRecord.dwell_ms > 0)
    )
    avg_dwell_ms = float(dwell_q.scalar_one_or_none() or 0.0)

    # ── Per-zone dwell breakdown ───────────────────────────────────────────────
    zone_q = await db.execute(
        select(
            EventRecord.zone_id,
            func.avg(EventRecord.dwell_ms).label("avg_dwell"),
            func.count(EventRecord.event_id).label("visit_count"),
        )
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.is_staff == False)
        .where(EventRecord.zone_id != None)
        .where(EventRecord.dwell_ms > 0)
        .group_by(EventRecord.zone_id)
    )
    zone_dwells = [
        ZoneDwell(
            zone_id=row.zone_id,
            avg_dwell_ms=float(row.avg_dwell),
            visit_count=row.visit_count,
        )
        for row in zone_q.fetchall()
    ]

    # ── Current queue depth ───────────────────────────────────────────────────
    queue_q = await db.execute(
        select(func.max(EventRecord.meta["queue_depth"].as_integer()))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "BILLING_QUEUE_JOIN")
    )
    queue_depth = queue_q.scalar_one_or_none() or 0

    # ── Abandonment rate ──────────────────────────────────────────────────────
    abandon_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "BILLING_QUEUE_ABANDON")
        .where(EventRecord.is_staff == False)
    )
    abandoned = abandon_q.scalar_one_or_none() or 0
    abandonment_rate = round(abandoned / billing_visitors, 4) if billing_visitors > 0 else 0.0

    log.info(
        "metrics.served",
        store_id=store_id,
        unique_visitors=unique_visitors,
        conversion_rate=conversion_rate,
        billing_visitors=billing_visitors,
        pos_transactions=len(pos_timestamps),
    )

    return MetricsResponse(
        store_id=store_id,
        unique_visitors=unique_visitors,
        conversion_rate=conversion_rate,
        avg_dwell_ms=avg_dwell_ms,
        zone_dwells=zone_dwells,
        queue_depth=queue_depth,
        abandonment_rate=abandonment_rate,
        as_of=datetime.now(timezone.utc),
    )