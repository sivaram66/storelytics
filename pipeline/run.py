"""
Run the full detection pipeline and feed events into the API.

Usage:
    python -m pipeline.run                    # detect + ingest
    python -m pipeline.run --detect-only      # just detect, save to JSONL
    python -m pipeline.run --ingest-only      # ingest existing JSONL into API
"""

import argparse
import json
import httpx
from pathlib import Path

from pipeline.detect import run_detection

API_BASE    = "http://localhost:8000"
EVENTS_PATH = Path("data/events/detected_events.jsonl")
BATCH_SIZE  = 100


def load_events(path: Path) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def ingest_events(events: list[dict]):
    print(f"📤 Ingesting {len(events)} events into API in batches of {BATCH_SIZE}...")
    total_accepted = 0
    total_dupes    = 0
    total_rejected = 0

    with httpx.Client(base_url=API_BASE, timeout=30) as client:
        for i in range(0, len(events), BATCH_SIZE):
            batch = events[i : i + BATCH_SIZE]
            resp  = client.post("/events/ingest", json={"events": batch})

            if resp.status_code == 200:
                data = resp.json()
                total_accepted += data["accepted"]
                total_dupes    += data["duplicates"]
                total_rejected += data["rejected"]
                print(f"  Batch {i//BATCH_SIZE + 1}: ✅ {data['accepted']} accepted, "
                      f"{data['duplicates']} dupes, {data['rejected']} rejected")
            else:
                print(f"  Batch {i//BATCH_SIZE + 1}: ❌ HTTP {resp.status_code} — {resp.text[:200]}")

    print(f"\n🎯 Total: {total_accepted} accepted | {total_dupes} duplicates | {total_rejected} rejected")


def main():
    parser = argparse.ArgumentParser(description="Storelytics Pipeline Runner")
    parser.add_argument("--detect-only", action="store_true", help="Only run detection, skip ingest")
    parser.add_argument("--ingest-only", action="store_true", help="Only ingest existing events, skip detection")
    args = parser.parse_args()

    if args.ingest_only:
        if not EVENTS_PATH.exists():
            print(f"❌ No events file found at {EVENTS_PATH}. Run detection first.")
            return
        events = load_events(EVENTS_PATH)
        ingest_events(events)
        return

    # Run detection
    events = run_detection()

    if not args.detect_only:
        ingest_events(events)


if __name__ == "__main__":
    main()