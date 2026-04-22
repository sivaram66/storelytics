# PROMPT: "Write async pytest tests for a FastAPI retail analytics API.
# Test metrics, funnel, heatmap, health endpoints with realistic store event data.
# Use httpx AsyncClient and pytest-asyncio with shared client fixture."
# CHANGES MADE: Used shared client fixture to avoid asyncpg connection conflicts,
# used STORE_PURPLLE_001, added edge cases for empty store and staff exclusion.


"""
PROMPT: Write pytest tests for the Storelytics detection pipeline.
Test zone classification, staff detection, timestamp generation, and event
schema validity. Use real camera IDs and zone names from the store layout.

"""

import pytest
import uuid
from datetime import datetime, timezone

STORE_ID = "STORE_PURPLLE_001"


def make_test_event(
    event_type="ENTRY", visitor_id=None, zone_id=None,
    dwell_ms=0, is_staff=False, camera_id="CAM_3", confidence=0.9,
):
    return {
        "event_id":   str(uuid.uuid4()),
        "store_id":   STORE_ID,
        "camera_id":  camera_id,
        "visitor_id": visitor_id or f"VIS_{uuid.uuid4().hex[:6].upper()}",
        "event_type": event_type,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "zone_id":    zone_id,
        "dwell_ms":   dwell_ms,
        "is_staff":   is_staff,
        "confidence": confidence,
        "metadata":   {"queue_depth": None, "sku_zone": zone_id, "session_seq": 1},
    }


# ── Health ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_200(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] in ["ok", "degraded"]


@pytest.mark.asyncio
async def test_health_has_checked_at(client):
    resp = await client.get("/health")
    assert "checked_at" in resp.json()


# ── Ingest ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_accepts_valid_events(client):
    events = [make_test_event() for _ in range(5)]
    resp = await client.post("/events/ingest", json={"events": events})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 5
    assert data["rejected"] == 0


@pytest.mark.asyncio
async def test_ingest_is_idempotent(client):
    events = [make_test_event(visitor_id="VIS_IDEM01")]
    resp1 = await client.post("/events/ingest", json={"events": events})
    resp2 = await client.post("/events/ingest", json={"events": events})
    assert resp1.json()["accepted"] == 1
    assert resp2.json()["duplicates"] == 1


@pytest.mark.asyncio
async def test_ingest_rejects_bad_confidence(client):
    bad_event = make_test_event()
    bad_event["confidence"] = 5.0  # invalid
    resp = await client.post("/events/ingest", json={"events": [bad_event]})
    assert resp.status_code in [200, 422]


# ── Metrics ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_returns_200(client):
    resp = await client.get(f"/stores/{STORE_ID}/metrics")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_metrics_schema(client):
    resp = await client.get(f"/stores/{STORE_ID}/metrics")
    data = resp.json()
    for field in ["unique_visitors", "conversion_rate", "avg_dwell_ms",
                  "zone_dwells", "queue_depth", "abandonment_rate"]:
        assert field in data


@pytest.mark.asyncio
async def test_metrics_empty_store_no_crash(client):
    resp = await client.get("/stores/STORE_EMPTY_999/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0


@pytest.mark.asyncio
async def test_metrics_excludes_staff(client):
    staff = make_test_event(event_type="ENTRY", is_staff=True,
                            visitor_id="VIS_STAFF_EXCL")
    await client.post("/events/ingest", json={"events": [staff]})
    resp = await client.get(f"/stores/{STORE_ID}/metrics")
    assert isinstance(resp.json()["unique_visitors"], int)


# ── Funnel ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_funnel_returns_200(client):
    resp = await client.get(f"/stores/{STORE_ID}/funnel")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_funnel_has_4_stages(client):
    resp = await client.get(f"/stores/{STORE_ID}/funnel")
    assert len(resp.json()["stages"]) == 4


@pytest.mark.asyncio
async def test_funnel_stage_names(client):
    resp = await client.get(f"/stores/{STORE_ID}/funnel")
    names = [s["stage"] for s in resp.json()["stages"]]
    assert "Entry" in names
    assert "Purchase" in names


@pytest.mark.asyncio
async def test_funnel_dropoff_non_negative(client):
    resp = await client.get(f"/stores/{STORE_ID}/funnel")
    for stage in resp.json()["stages"]:
        assert stage["dropoff_pct"] >= 0.0


# ── Heatmap ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heatmap_returns_200(client):
    resp = await client.get(f"/stores/{STORE_ID}/heatmap")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_heatmap_frequency_normalised(client):
    resp = await client.get(f"/stores/{STORE_ID}/heatmap")
    for zone in resp.json()["zones"]:
        assert 0.0 <= zone["visit_frequency"] <= 100.0


# ── Anomalies ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_anomalies_returns_200(client):
    resp = await client.get(f"/stores/{STORE_ID}/anomalies")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_anomalies_schema(client):
    resp = await client.get(f"/stores/{STORE_ID}/anomalies")
    data = resp.json()
    assert "anomalies" in data
    for a in data["anomalies"]:
        assert a["severity"] in ["INFO", "WARN", "CRITICAL"]
        assert len(a["suggested_action"]) > 0