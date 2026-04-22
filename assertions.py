import json
import sys
from pathlib import Path

VALID_EVENT_TYPES = {
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
}

REQUIRED_FIELDS = [
    "event_id", "store_id", "camera_id", "visitor_id",
    "event_type", "timestamp", "zone_id", "dwell_ms",
    "is_staff", "confidence", "metadata"
]

EVENTS_FILE = Path("data/events/detected_events.jsonl")

def run_assertions():
    print("Running Storelytics assertions...")
    assert EVENTS_FILE.exists(), f"FAIL: {EVENTS_FILE} not found"
    events = []
    with open(EVENTS_FILE) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError as e:
                print(f"FAIL: Line {i} is not valid JSON: {e}")
                sys.exit(1)
    print(f"  Loaded {len(events)} events")
    event_ids = set()
    for i, event in enumerate(events, 1):
        for field in REQUIRED_FIELDS:
            assert field in event, f"FAIL: Event {i} missing field {field}"
        assert event["event_id"] not in event_ids, f"FAIL: Duplicate event_id"
        event_ids.add(event["event_id"])
        assert event["event_type"] in VALID_EVENT_TYPES, f"FAIL: Invalid event_type {event['event_type']}"
        assert 0.0 <= event["confidence"] <= 1.0, "FAIL: confidence out of range"
        assert event["dwell_ms"] >= 0, "FAIL: dwell_ms is negative"
        assert isinstance(event["is_staff"], bool), "FAIL: is_staff must be boolean"
        assert event["store_id"] == "STORE_PURPLLE_001", "FAIL: wrong store_id"
        assert isinstance(event["metadata"], dict), "FAIL: metadata must be dict"
    print(f"  All {len(events)} events passed schema validation")
    print(f"  Unique event_ids: {len(event_ids)}")
    print(f"  Event types: {set(e['event_type'] for e in events)}")
    print("PASS: All assertions passed!")

if __name__ == "__main__":
    run_assertions()
