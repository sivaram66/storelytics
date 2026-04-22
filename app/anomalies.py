from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from datetime import datetime, timezone, timedelta
import os
import structlog

from app.database import get_db, EventRecord
from app.models import AnomalyResponse, Anomaly

router = APIRouter()
log = structlog.get_logger()

QUEUE_SPIKE_THRESHOLD  = int(os.getenv("ANOMALY_QUEUE_SPIKE_THRESHOLD", 5))
CONVERSION_DROP_THRESHOLD = float(os.getenv("ANOMALY_CONVERSION_DROP_THRESHOLD", 0.3))
DEAD_ZONE_MINUTES      = int(os.getenv("DEAD_ZONE_MINUTES", 30))


@router.get("/stores/{store_id}/anomalies", response_model=AnomalyResponse)
async def get_anomalies(store_id: str, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    anomalies = []

    # ── 1. Queue Spike ────────────────────────────────────────────────────────
    queue_q = await db.execute(
        select(func.max(EventRecord.meta["queue_depth"].as_integer()))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "BILLING_QUEUE_JOIN")
        .where(EventRecord.timestamp >= now - timedelta(minutes=15))
    )
    current_queue = queue_q.scalar_one_or_none() or 0

    if current_queue >= QUEUE_SPIKE_THRESHOLD:
        severity = "CRITICAL" if current_queue >= QUEUE_SPIKE_THRESHOLD * 2 else "WARN"
        anomalies.append(Anomaly(
            anomaly_type="BILLING_QUEUE_SPIKE",
            severity=severity,
            description=f"Queue depth is {current_queue} at billing counter.",
            suggested_action="Deploy additional billing staff immediately." if severity == "CRITICAL" else "Monitor billing queue — consider opening additional counter.",
            detected_at=now,
        ))

    # ── 2. Conversion Drop vs 7-day average ───────────────────────────────────
    seven_days_ago = now - timedelta(days=7)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Today's conversion
    today_entry_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "ENTRY")
        .where(EventRecord.is_staff == False)
        .where(EventRecord.timestamp >= today_start)
    )
    today_entries = today_entry_q.scalar_one_or_none() or 0

    today_billing_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "BILLING_QUEUE_JOIN")
        .where(EventRecord.is_staff == False)
        .where(EventRecord.timestamp >= today_start)
    )
    today_billing = today_billing_q.scalar_one_or_none() or 0
    today_conversion = today_billing / today_entries if today_entries > 0 else 0.0

    # 7-day average conversion
    hist_entry_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "ENTRY")
        .where(EventRecord.is_staff == False)
        .where(EventRecord.timestamp >= seven_days_ago)
        .where(EventRecord.timestamp < today_start)
    )
    hist_entries = hist_entry_q.scalar_one_or_none() or 0

    hist_billing_q = await db.execute(
        select(func.count(distinct(EventRecord.visitor_id)))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "BILLING_QUEUE_JOIN")
        .where(EventRecord.is_staff == False)
        .where(EventRecord.timestamp >= seven_days_ago)
        .where(EventRecord.timestamp < today_start)
    )
    hist_billing = hist_billing_q.scalar_one_or_none() or 0
    hist_conversion = hist_billing / hist_entries if hist_entries > 0 else 0.0

    if hist_conversion > 0 and (hist_conversion - today_conversion) / hist_conversion >= CONVERSION_DROP_THRESHOLD:
        anomalies.append(Anomaly(
            anomaly_type="CONVERSION_DROP",
            severity="WARN",
            description=f"Today's conversion {today_conversion:.1%} is significantly below 7-day avg {hist_conversion:.1%}.",
            suggested_action="Review floor staff positioning and check for any product availability issues.",
            detected_at=now,
        ))

    # ── 3. Dead Zone — no visits in last 30 minutes ───────────────────────────
    cutoff = now - timedelta(minutes=DEAD_ZONE_MINUTES)
    active_zones_q = await db.execute(
        select(distinct(EventRecord.zone_id))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.event_type == "ZONE_ENTER")
        .where(EventRecord.timestamp >= cutoff)
        .where(EventRecord.zone_id != None)
    )
    recently_active = {row[0] for row in active_zones_q.fetchall()}

    all_zones_q = await db.execute(
        select(distinct(EventRecord.zone_id))
        .where(EventRecord.store_id == store_id)
        .where(EventRecord.zone_id != None)
    )
    all_zones = {row[0] for row in all_zones_q.fetchall()}

    dead_zones = all_zones - recently_active
    for zone in dead_zones:
        anomalies.append(Anomaly(
            anomaly_type="DEAD_ZONE",
            severity="INFO",
            description=f"Zone '{zone}' has had no customer visits in the last {DEAD_ZONE_MINUTES} minutes.",
            suggested_action=f"Check if zone '{zone}' display is appealing. Consider repositioning promotional material.",
            detected_at=now,
        ))

    log.info("anomalies.served", store_id=store_id, count=len(anomalies))

    return AnomalyResponse(store_id=store_id, anomalies=anomalies, as_of=now) 