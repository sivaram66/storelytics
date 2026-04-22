# PROMPT: "Write pytest tests for a retail CV pipeline event schema validator.
# Test event structure, field types, UUID uniqueness, timestamp format,
# confidence range, staff flagging, and zone classification."
# CHANGES MADE: Added Purplle-specific store/camera IDs, adjusted confidence
# thresholds to match our 0.35 detection threshold, added JSONL file test.

"""
PROMPT: Write pytest tests for the Store Intelligence detection pipeline.
Test zone classification, staff detection, timestamp generation, and event
schema validity. Use real camera IDs and zone names from the store layout.
"""

import pytest
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

from pipeline.emit import make_event, emit_entry, emit_exit, emit_zone_enter, emit_billing_join
from pipeline.tracker import (
    make_visitor_id, DirectionDetector,
    StaffDetector, ZoneClassifier,
    DwellTracker, QueueTracker, SessionTracker
)

STORE_ID  = "STORE_PURPLLE_001"
CAM_ENTRY = "CAM_3"
CAM_FLOOR = "CAM_1"
CAM_STOCK = "CAM_4"
CAM_BILL  = "CAM_5"


# ── Schema tests ───────────────────────────────────────────────────────────────

class TestEventSchema:

    def test_make_event_has_required_fields(self):
        event = make_event(
            camera_id="CAM_1", visitor_id="VIS_ABC123",
            event_type="ENTRY", timestamp="2026-04-10T14:30:00Z",
        )
        required = ["event_id", "store_id", "camera_id", "visitor_id",
                    "event_type", "timestamp", "zone_id", "dwell_ms",
                    "is_staff", "confidence", "metadata"]
        for field in required:
            assert field in event, f"Missing field: {field}"

    def test_event_id_is_valid_uuid(self):
        event = make_event(
            camera_id="CAM_1", visitor_id="VIS_ABC123",
            event_type="ENTRY", timestamp="2026-04-10T14:30:00Z",
        )
        parsed = uuid.UUID(event["event_id"])
        assert parsed.version == 4

    def test_event_ids_are_unique(self):
        events = [
            make_event("CAM_1", "VIS_ABC123", "ENTRY", "2026-04-10T14:30:00Z")
            for _ in range(100)
        ]
        ids = [e["event_id"] for e in events]
        assert len(set(ids)) == 100

    def test_confidence_within_range(self):
        event = make_event(
            camera_id="CAM_1", visitor_id="VIS_ABC123",
            event_type="ZONE_ENTER", timestamp="2026-04-10T14:30:00Z",
            confidence=0.87,
        )
        assert 0.0 <= event["confidence"] <= 1.0

    def test_store_id_is_correct(self):
        event = make_event(
            camera_id="CAM_1", visitor_id="VIS_ABC123",
            event_type="ENTRY", timestamp="2026-04-10T14:30:00Z",
        )
        assert event["store_id"] == STORE_ID

    def test_dwell_ms_default_zero(self):
        event = make_event(
            camera_id="CAM_1", visitor_id="VIS_ABC123",
            event_type="ENTRY", timestamp="2026-04-10T14:30:00Z",
        )
        assert event["dwell_ms"] == 0

    def test_metadata_structure(self):
        event = make_event(
            camera_id=CAM_BILL, visitor_id="VIS_ABC123",
            event_type="BILLING_QUEUE_JOIN", timestamp="2026-04-10T14:30:00Z",
            queue_depth=3,
        )
        assert "queue_depth" in event["metadata"]
        assert event["metadata"]["queue_depth"] == 3


# ── Visitor ID tests ───────────────────────────────────────────────────────────

class TestVisitorID:

    def test_visitor_id_format(self):
        vid = make_visitor_id(42, "CAM_1")
        assert vid.startswith("VIS_")
        assert len(vid) == 10

    def test_same_input_same_id(self):
        vid1 = make_visitor_id(42, "CAM_1")
        vid2 = make_visitor_id(42, "CAM_1")
        assert vid1 == vid2

    def test_different_cameras_different_ids(self):
        vid1 = make_visitor_id(1, "CAM_1")
        vid2 = make_visitor_id(1, "CAM_2")
        assert vid1 != vid2


# ── Direction detector tests ───────────────────────────────────────────────────

class TestDirectionDetector:

    def test_entry_detected_moving_down(self):
        dd = DirectionDetector(threshold_px=20)
        result = None
        for y in [100, 115, 130, 145, 160]:
            result = dd.update(track_id=1, cy=float(y))
        assert result == "ENTRY"

    def test_exit_detected_moving_up(self):
        dd = DirectionDetector(threshold_px=20)
        result = None
        for y in [400, 380, 360, 340, 320]:
            result = dd.update(track_id=1, cy=float(y))
        assert result == "EXIT"

    def test_no_result_insufficient_movement(self):
        dd = DirectionDetector(threshold_px=50)
        result = None
        for y in [200, 202, 201, 203, 204]:
            result = dd.update(track_id=1, cy=float(y))
        assert result is None


# ── Staff detector tests ───────────────────────────────────────────────────────

class TestStaffDetector:

    def test_stockroom_always_staff(self):
        sd = StaffDetector()
        assert sd.is_staff(CAM_STOCK) is True

    def test_floor_cam_not_auto_staff(self):
        sd = StaffDetector()
        assert sd.is_staff(CAM_FLOOR, crop_rgb=None) is False

    def test_dark_uniform_detected(self):
        import numpy as np
        sd = StaffDetector()
        dark_crop = np.full((100, 50, 3), 40, dtype=np.uint8)
        assert sd.is_staff(CAM_FLOOR, crop_rgb=dark_crop) is True

    def test_bright_clothing_not_staff(self):
        import numpy as np
        sd = StaffDetector()
        bright_crop = np.full((100, 50, 3), 180, dtype=np.uint8)
        assert sd.is_staff(CAM_FLOOR, crop_rgb=bright_crop) is False


# ── Zone classifier tests ──────────────────────────────────────────────────────

class TestZoneClassifier:

    def test_cam1_always_skincare(self):
        zc = ZoneClassifier()
        assert zc.get_zone("CAM_1", 400, 300, 1280, 720) == "SKINCARE"

    def test_cam2_left_is_makeup(self):
        zc = ZoneClassifier()
        assert zc.get_zone("CAM_2", 300, 300, 1280, 720) == "MAKEUP"

    def test_cam2_right_is_accessories(self):
        zc = ZoneClassifier()
        assert zc.get_zone("CAM_2", 900, 300, 1280, 720) == "ACCESSORIES"

    def test_cam5_is_billing(self):
        zc = ZoneClassifier()
        assert zc.get_zone("CAM_5", 640, 360, 1280, 720) == "BILLING"


# ── Dwell tracker tests ────────────────────────────────────────────────────────

class TestDwellTracker:

    def test_no_dwell_before_threshold(self):
        dt = DwellTracker(dwell_interval_ms=30_000)
        dt.enter_zone("VIS_001", "SKINCARE", 0)
        result = dt.check_dwell("VIS_001", 15_000)
        assert result is None

    def test_dwell_emitted_after_threshold(self):
        dt = DwellTracker(dwell_interval_ms=30_000)
        dt.enter_zone("VIS_001", "SKINCARE", 0)
        result = dt.check_dwell("VIS_001", 31_000)
        assert result is not None
        zone_id, dwell_ms = result
        assert zone_id == "SKINCARE"
        assert dwell_ms >= 30_000

    def test_exit_returns_dwell(self):
        dt = DwellTracker()
        dt.enter_zone("VIS_001", "MAKEUP", 0)
        result = dt.exit_zone("VIS_001", 10_000)
        assert result is not None
        zone_id, dwell_ms = result
        assert zone_id == "MAKEUP"
        assert dwell_ms == 10_000


# ── Queue tracker tests ────────────────────────────────────────────────────────

class TestQueueTracker:

    def test_queue_depth_increases(self):
        qt = QueueTracker()
        assert qt.enter("VIS_001") == 1
        assert qt.enter("VIS_002") == 2
        assert qt.enter("VIS_003") == 3

    def test_queue_depth_decreases_on_exit(self):
        qt = QueueTracker()
        qt.enter("VIS_001")
        qt.enter("VIS_002")
        assert qt.exit("VIS_001") == 1

    def test_duplicate_enter_not_counted(self):
        qt = QueueTracker()
        qt.enter("VIS_001")
        qt.enter("VIS_001")
        assert qt.depth == 1


# ── Session tracker tests ──────────────────────────────────────────────────────

class TestSessionTracker:

    def test_first_visit_is_session_1(self):
        st = SessionTracker()
        seq = st.enter("VIS_001")
        assert seq == 1

    def test_reentry_increments_session(self):
        st = SessionTracker()
        st.enter("VIS_001")
        st.exit("VIS_001")
        seq = st.enter("VIS_001")
        assert seq == 2

    def test_no_exit_no_reentry(self):
        st = SessionTracker()
        st.enter("VIS_001")
        seq = st.enter("VIS_001")
        assert seq == 1


# ── JSONL output tests ─────────────────────────────────────────────────────────

class TestJSONLOutput:

    def test_events_file_exists(self):
        path = Path("data/events/detected_events.jsonl")
        assert path.exists(), "detected_events.jsonl not found — run pipeline first"

    def test_events_are_valid_json(self):
        path = Path("data/events/detected_events.jsonl")
        if not path.exists():
            pytest.skip("No events file")
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    event = json.loads(line)
                    assert "event_id" in event

    def test_all_events_have_store_id(self):
        path = Path("data/events/detected_events.jsonl")
        if not path.exists():
            pytest.skip("No events file")
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    event = json.loads(line)
                    assert event["store_id"] == STORE_ID

    def test_no_duplicate_event_ids(self):
        path = Path("data/events/detected_events.jsonl")
        if not path.exists():
            pytest.skip("No events file")
        ids = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    ids.append(json.loads(line)["event_id"])
        assert len(ids) == len(set(ids)), "Duplicate event_ids found!"