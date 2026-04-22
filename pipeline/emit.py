import uuid
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── Load store layout ──────────────────────────────────────────────────────────

LAYOUT_PATH = Path(__file__).parent.parent / "data" / "store_layout.json"
with open(LAYOUT_PATH) as f:
    STORE_LAYOUT = json.load(f)

STORE_ID  = STORE_LAYOUT["store_id"]

# Camera role lookup
CAM_ROLES = {k: v["role"] for k, v in STORE_LAYOUT["cameras"].items()}
CAM_ZONES = {k: v["zones_covered"][0] for k, v in STORE_LAYOUT["cameras"].items()}

# Stockroom cameras — anyone here is staff
STAFF_ONLY_CAMS = {
    k for k, v in STORE_LAYOUT["cameras"].items()
    if v["role"] == "stockroom"
}


# ── Timestamp from video frame ─────────────────────────────────────────────────

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def frame_to_timestamp(clip_start: datetime, frame_idx: int, fps: float) -> str:
    offset_seconds = frame_idx / fps
    ts = clip_start + timedelta(seconds=offset_seconds)
    ts_ist = ts.astimezone(IST)
    return ts_ist.strftime("%Y-%m-%dT%H:%M:%S+05:30")

# ── Event builders ─────────────────────────────────────────────────────────────

def make_event(
    camera_id:  str,
    visitor_id: str,
    event_type: str,
    timestamp:  str,
    zone_id:    str  = None,
    dwell_ms:   int  = 0,
    is_staff:   bool = False,
    confidence: float = 0.9,
    queue_depth: int = None,
    session_seq: int = 0,
) -> dict:
    return {
        "event_id":   str(uuid.uuid4()),
        "store_id":   STORE_ID,
        "camera_id":  camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp":  timestamp,
        "zone_id":    zone_id,
        "dwell_ms":   dwell_ms,
        "is_staff":   is_staff,
        "confidence": round(confidence, 3),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone":    zone_id,
            "session_seq": session_seq,
        }
    }


def emit_entry(camera_id, visitor_id, timestamp, confidence, is_staff=False, session_seq=0):
    return make_event(
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type="REENTRY" if session_seq > 1 else "ENTRY",
        timestamp=timestamp,
        zone_id=None,
        is_staff=is_staff,
        confidence=confidence,
        session_seq=session_seq,
    )


def emit_exit(camera_id, visitor_id, timestamp, confidence, is_staff=False, session_seq=0):
    return make_event(
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type="EXIT",
        timestamp=timestamp,
        zone_id=None,
        is_staff=is_staff,
        confidence=confidence,
        session_seq=session_seq,
    )


def emit_zone_enter(camera_id, visitor_id, timestamp, zone_id, confidence, is_staff=False, session_seq=0):
    return make_event(
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type="ZONE_ENTER",
        timestamp=timestamp,
        zone_id=zone_id,
        is_staff=is_staff,
        confidence=confidence,
        session_seq=session_seq,
    )


def emit_zone_dwell(camera_id, visitor_id, timestamp, zone_id, dwell_ms, confidence, is_staff=False, session_seq=0):
    return make_event(
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type="ZONE_DWELL",
        timestamp=timestamp,
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=confidence,
        session_seq=session_seq,
    )


def emit_billing_join(camera_id, visitor_id, timestamp, queue_depth, confidence, session_seq=0):
    return make_event(
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type="BILLING_QUEUE_JOIN",
        timestamp=timestamp,
        zone_id="BILLING",
        queue_depth=queue_depth,
        confidence=confidence,
        session_seq=session_seq,
    )


def emit_billing_abandon(camera_id, visitor_id, timestamp, confidence, session_seq=0):
    return make_event(
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type="BILLING_QUEUE_ABANDON",
        timestamp=timestamp,
        zone_id="BILLING",
        confidence=confidence,
        session_seq=session_seq,
    )


# ── Save events to JSONL ───────────────────────────────────────────────────────

def save_events(events: list[dict], output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    print(f"✅ Saved {len(events)} events to {output_path}")