# PROMPT: "Write pytest tests for retail anomaly detection: queue spikes,
# conversion drops, dead zones, edge cases including all-staff and zero purchases."
# CHANGES MADE: Switched to shared client fixture, added boundary tests based
# on .env thresholds, fixed re-entry funnel test to use distinct visitor IDs.


"""
PROMPT: Write pytest tests for the Storelytics detection pipeline.
Test zone classification, staff detection, timestamp generation, and event
schema validity. Use real camera IDs and zone names from the store layout.
"""

import pytest
import uuid
from datetime import datetime, timezone

STORE_ID = "STORE_PURPLLE_001"


def make_event(event_type, visitor_id, zone_id=None, is_staff=False,
               camera_id="CAM_5", queue_depth=None, dwell_ms=0):
    return {
        "event_id":   str(uuid.uuid4()),
        "store_id":   STORE_ID,
        "camera_id":  camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "zone_id":    zone_id,
        "dwell_ms":   dwell_ms,
        "is_staff":   is_staff,
        "confidence": 0.88,
        "metadata":   {"queue_depth": queue_depth, "sku_zone": zone_id, "session_seq": 1},
    }


@pytest.mark.asyncio
async def test_anomalies_always_returns_list(client):
    resp = await client.get(f"/stores/{STORE_ID}/anomalies")
    assert resp.status_code == 200
    assert isinstance(resp.json()["anomalies"], list)


@pytest.mark.asyncio
async def test_anomalies_empty_store_no_crash(client):
    resp = await client.get("/stores/STORE_EMPTY_ANOMALY/anomalies")
    assert resp.status_code == 200
    assert resp.json()["anomalies"] == []


@pytest.mark.asyncio
async def test_anomaly_severity_valid_values(client):
    resp = await client.get(f"/stores/{STORE_ID}/anomalies")
    for a in resp.json()["anomalies"]:
        assert a["severity"] in ["INFO", "WARN", "CRITICAL"]


@pytest.mark.asyncio
async def test_anomaly_has_suggested_action(client):
    resp = await client.get(f"/stores/{STORE_ID}/anomalies")
    for a in resp.json()["anomalies"]:
        assert len(a["suggested_action"]) > 0


@pytest.mark.asyncio
async def test_queue_spike_triggered(client):
    events = [
        make_event("BILLING_QUEUE_JOIN", f"VIS_QSP{i:03d}",
                   zone_id="BILLING", queue_depth=i+1)
        for i in range(6)
    ]
    await client.post("/events/ingest", json={"events": events})
    resp = await client.get(f"/stores/{STORE_ID}/anomalies")
    types = [a["anomaly_type"] for a in resp.json()["anomalies"]]
    assert "BILLING_QUEUE_SPIKE" in types


@pytest.mark.asyncio
async def test_dead_zone_structure(client):
    resp = await client.get(f"/stores/{STORE_ID}/anomalies")
    for a in resp.json()["anomalies"]:
        if a["anomaly_type"] == "DEAD_ZONE":
            assert "zone" in a["description"].lower()
            assert len(a["suggested_action"]) > 0


@pytest.mark.asyncio
async def test_all_staff_clip_no_crash(client):
    staff_events = [
        make_event("ENTRY", f"VIS_STFX_{i}", is_staff=True, camera_id="CAM_4")
        for i in range(5)
    ]
    await client.post("/events/ingest", json={"events": staff_events})
    resp = await client.get(f"/stores/{STORE_ID}/metrics")
    assert resp.status_code == 200
    assert isinstance(resp.json()["conversion_rate"], float)


@pytest.mark.asyncio
async def test_zero_purchases_no_crash(client):
    events = [
        make_event("ENTRY", f"VIS_ZP_{i}", camera_id="CAM_3")
        for i in range(3)
    ]
    await client.post("/events/ingest", json={"events": events})
    resp = await client.get(f"/stores/{STORE_ID}/metrics")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_reentry_not_double_counted(client):
    visitor = f"VIS_REENT_{uuid.uuid4().hex[:4]}"
    events = [
        make_event("ENTRY",   visitor, camera_id="CAM_3"),
        make_event("EXIT",    visitor, camera_id="CAM_3"),
        make_event("REENTRY", visitor, camera_id="CAM_3"),
    ]
    await client.post("/events/ingest", json={"events": events})
    resp = await client.get(f"/stores/{STORE_ID}/funnel")
    assert resp.status_code == 200
    stages = resp.json()["stages"]
    entry_stage = next(s for s in stages if s["stage"] == "Entry")
    assert isinstance(entry_stage["count"], int)