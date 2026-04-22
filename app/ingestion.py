from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timezone
import json
import structlog

from app.database import get_db, EventRecord
from app.models import StoreEvent, IngestResponse

router = APIRouter()
log = structlog.get_logger()


def parse_timestamp(ts) -> datetime:
    """Ensure timestamp is timezone-aware datetime."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    if isinstance(ts, str):
        ts = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return ts


def parse_body(raw: bytes) -> list[dict]:
    """
    Detect format and return list of event dicts.

    Fix 1 — Always try JSON first, then fall back to JSONL.
    This correctly handles multi-line JSON arrays like:
    [
      {...},
      {...}
    ]
    which would be wrongly detected as JSONL if we checked line count first.

    Supported formats:
      JSON:  {"events": [{...}, {...}]}
      JSON:  [{...}, {...}]
      JSONL: {"event_id": "1",...}\n{"event_id": "2",...}
    """
    text = raw.decode("utf-8").strip()

    # ── Try JSON first (handles both single-line and multi-line JSON) ──────────
    try:
        data = json.loads(text)

        if isinstance(data, dict) and "events" in data:
            return data["events"]

        if isinstance(data, list):
            return data

    except json.JSONDecodeError:
        pass

    # ── Fallback: JSONL — one JSON object per line ─────────────────────────────
    return [
        json.loads(line)
        for line in text.splitlines()
        if line.strip()
    ]


@router.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(request: Request, db: AsyncSession = Depends(get_db)):
    accepted   = 0
    duplicates = 0
    rejected   = 0
    errors     = []

    # ── Parse raw body ─────────────────────────────────────────────────────────
    try:
        raw         = await request.body()
        event_dicts = parse_body(raw)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={
                "accepted": 0, "duplicates": 0, "rejected": 0,
                "errors": [{"event_id": "unknown", "error": f"Parse error: {str(e)}"}]
            }
        )

    # ── Validate and ingest each event ────────────────────────────────────────
    for event_dict in event_dicts:
        try:
            # Pydantic validation
            event = StoreEvent(**event_dict)

            # Fix 2 + Fix 3 — Use PostgreSQL INSERT ... ON CONFLICT DO NOTHING
            # This lets the DB handle duplicates via UNIQUE constraint on event_id
            # Much faster than SELECT first — no extra query per event
            stmt = pg_insert(EventRecord).values(
                event_id   = event.event_id,
                store_id   = event.store_id,
                camera_id  = event.camera_id,
                visitor_id = event.visitor_id,
                event_type = event.event_type,
                timestamp  = parse_timestamp(event.timestamp),
                zone_id    = event.zone_id,
                dwell_ms   = event.dwell_ms,
                is_staff   = event.is_staff,
                confidence = event.confidence,
                meta       = event.metadata.model_dump(),
            ).on_conflict_do_nothing(index_elements=["event_id"])

            result = await db.execute(stmt)

            # rowcount 0 = duplicate (conflict), 1 = inserted
            if result.rowcount == 0:
                duplicates += 1
            else:
                accepted += 1

        except Exception as e:
            rejected += 1
            errors.append({
                "event_id": event_dict.get("event_id", "unknown"),
                "error": str(e)
            })

    # Fix 2 — Single commit outside loop (clean transaction)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        log.error("ingest.commit_failed", error=str(e))

    log.info("ingest.complete",
             accepted=accepted, duplicates=duplicates, rejected=rejected)

    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
        errors=errors,
    )