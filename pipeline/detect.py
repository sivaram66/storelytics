import cv2
import json
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from ultralytics import YOLO

from pipeline.tracker import (
    DirectionDetector, ZoneClassifier,
    StaffDetector, DwellTracker,
    QueueTracker, SessionTracker,
    make_visitor_id,
)
from pipeline.emit import (
    frame_to_timestamp, emit_entry, emit_exit,
    emit_zone_enter, emit_zone_dwell,
    emit_billing_join, emit_billing_abandon,
    save_events, CAM_ZONES, STAFF_ONLY_CAMS,
)

# ── Config ─────────────────────────────────────────────────────────────────────

MODEL_PATH  = "yolov8n.pt"
CLIPS_DIR   = Path("data/clips")
EVENTS_DIR  = Path("data/events")
CONF_THRESH = 0.45        # raised from 0.35 to reduce false positives
IOU_THRESH  = 0.45
FRAME_SKIP  = 2           # every 2nd frame for better tracking
MIN_TRACK_FRAMES = 8      # ignore tracks shorter than this — removes false positives

# ── Camera config with real timestamps ────────────────────────────────────────
CAMERA_CONFIG = {
    "CAM_1": {
        "file": "CAM 1.mp4",
        "role": "main_floor",
        "clip_start": "2026-04-10T20:10:28+05:30",
        "tripwire_y": None,
        "min_track_frames": MIN_TRACK_FRAMES,
    },
    "CAM_2": {
        "file": "CAM 2.mp4",
        "role": "main_floor",
        "clip_start": "2026-04-10T20:10:03+05:30",
        "tripwire_y": None,
        "min_track_frames": 15,
        "zone_debounce_ms": 8000,
    },
    "CAM_3": {
        "file": "CAM 3.mp4",
        "role": "entry_exit",
        "clip_start": "2026-04-10T20:10:00+05:30",
        "tripwire_y": 0.60,
        "min_track_frames": 12,
    },
    "CAM_4": {
        "file": "CAM 4.mp4",
        "role": "stockroom",
        "clip_start": "2026-04-10T20:10:28+05:30",
        "tripwire_y": None,
        "min_track_frames": MIN_TRACK_FRAMES,
    },
    "CAM_5": {
        "file": "CAM 5.mp4",
        "role": "billing",
        "clip_start": "2026-04-10T20:10:11+05:30",
        "tripwire_y": None,
        "min_track_frames": MIN_TRACK_FRAMES,
    },
}


# ── Tripwire ───────────────────────────────────────────────────────────────────

class TripwireDetector:
    """
    Virtual line across the frame.
    A person is counted as crossing only when their bbox center
    crosses from one side of the line to the other.
    Prevents counting people visible through glass outside the store.
    """
    def __init__(self, tripwire_y_ratio: float, frame_h: int):
        self.line_y = int(tripwire_y_ratio * frame_h)
        self.prev_side: dict[int, str] = {}  # track_id -> "above" or "below"
        self.crossed: set[int] = set()       # track_ids that already crossed

    def update(self, track_id: int, cy: float) -> str | None:
        # Already counted this person
        if track_id in self.crossed:
            return None

        current_side = "below" if cy > self.line_y else "above"
        prev = self.prev_side.get(track_id)

        self.prev_side[track_id] = current_side

        if prev is None:
            return None

        if prev == "above" and current_side == "below":
            self.crossed.add(track_id)
            return "ENTRY"  # crossed line moving downward = entering store

        if prev == "below" and current_side == "above":
            self.crossed.add(track_id)
            return "EXIT"   # crossed line moving upward = exiting store

        return None


# ── Process one clip ───────────────────────────────────────────────────────────

def process_clip(camera_id: str, config: dict, model: YOLO) -> list[dict]:
    clip_path = CLIPS_DIR / config["file"]
    if not clip_path.exists():
        print(f"⚠️  Clip not found: {clip_path}")
        return []

    clip_start = datetime.fromisoformat(config["clip_start"])
    role         = config["role"]
    is_entry_cam = role == "entry_exit"
    is_billing   = role == "billing"
    tripwire_y   = config.get("tripwire_y")
    min_frames   = config.get("min_track_frames", MIN_TRACK_FRAMES)

    cap     = cv2.VideoCapture(str(clip_path))
    fps     = cap.get(cv2.CAP_PROP_FPS) or 15.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # ── Trackers ───────────────────────────────────────────────────────────────
    zone_clf    = ZoneClassifier()
    staff_det   = StaffDetector()
    dwell_trk   = DwellTracker()
    queue_trk   = QueueTracker()
    session_trk = SessionTracker()
    tripwire    = TripwireDetector(tripwire_y, frame_h) if tripwire_y else None

    events         = []
    frame_idx      = 0
    active_tracks  = {}        # track_id -> zone_id
    last_zone_enter: dict[str, tuple[str, float]] = {}
    ZONE_ENTER_DEBOUNCE_MS = config.get("zone_debounce_ms", 5000)
    track_frame_count = {}     # track_id -> how many frames seen
    track_crops    = {}        # track_id -> last crop for staff detection

    print(f"🎬 Processing {camera_id} ({config['file']})...")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        if frame_idx % FRAME_SKIP != 0:
            continue

        current_ms = (frame_idx / fps) * 1000
        timestamp  = frame_to_timestamp(clip_start, frame_idx, fps)

        # ── YOLO tracking ──────────────────────────────────────────────────────
        results = model.track(
            frame,
            persist=True,
            conf=CONF_THRESH,
            iou=IOU_THRESH,
            classes=[0],
            verbose=False,
        )

        current_ids = set()

        for result in results:
            if result.boxes is None or result.boxes.id is None:
                continue

            boxes = result.boxes.xyxy.cpu().numpy()
            ids   = result.boxes.id.cpu().numpy().astype(int)
            confs = result.boxes.conf.cpu().numpy()

            for box, track_id, conf in zip(boxes, ids, confs):
                x1, y1, x2, y2 = box
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2

                current_ids.add(track_id)

                # Count frames this track has been seen
                track_frame_count[track_id] = track_frame_count.get(track_id, 0) + 1

                # Ignore tracks that haven't been seen enough frames
                # This removes false positives from people visible through glass
                if track_frame_count[track_id] < min_frames:
                    continue

                visitor_id = make_visitor_id(track_id, camera_id)

                # ── Staff detection ────────────────────────────────────────────
                crop = frame[int(y1):int(y2), int(x1):int(x2)]
                crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB) if crop.size > 0 else None
                if crop_rgb is not None:
                    track_crops[track_id] = crop_rgb
                is_staff = staff_det.is_staff(camera_id, track_crops.get(track_id))

                # ── Entry/exit camera — use tripwire ───────────────────────────
                if is_entry_cam and tripwire:
                    crossing = tripwire.update(track_id, cy)
                    if crossing:
                        seq = session_trk.enter(visitor_id) if crossing == "ENTRY" else session_trk.get_seq(visitor_id)
                        if crossing == "ENTRY":
                            events.append(emit_entry(
                                camera_id, visitor_id, timestamp,
                                float(conf), is_staff, seq
                            ))
                            print(f"  ✅ ENTRY detected: {visitor_id} (staff={is_staff})")
                        else:
                            session_trk.exit(visitor_id)
                            events.append(emit_exit(
                                camera_id, visitor_id, timestamp,
                                float(conf), is_staff, seq
                            ))
                            print(f"  ✅ EXIT detected: {visitor_id}")
                    continue  # entry cam only does entry/exit, not zone events

                # ── Zone cameras — first time seeing this track ────────────────
                # ── Zone cameras — first time seeing this track ────────────────
                if track_id not in active_tracks:
                    active_tracks[track_id] = None
                    zone_id = zone_clf.get_zone(camera_id, cx, cy, frame_w, frame_h)
                    seq = session_trk.get_seq(visitor_id)

                    # Debounce — only emit if not seen recently in same zone
                    last = last_zone_enter.get(visitor_id)
                    should_emit = (
                        last is None or
                        last[0] != zone_id or
                        (current_ms - last[1]) > ZONE_ENTER_DEBOUNCE_MS
                    )

                    if should_emit:
                        events.append(emit_zone_enter(
                            camera_id, visitor_id, timestamp,
                            zone_id, float(conf), is_staff, seq
                        ))
                        last_zone_enter[visitor_id] = (zone_id, current_ms)

                    dwell_trk.enter_zone(visitor_id, zone_id, current_ms)
                    active_tracks[track_id] = zone_id

                    if is_billing and not is_staff:
                        depth = queue_trk.enter(visitor_id)
                        events.append(emit_billing_join(
                            camera_id, visitor_id, timestamp,
                            depth, float(conf), seq
                        ))

                # ── Dwell check ────────────────────────────────────────────────
                dwell_result = dwell_trk.check_dwell(visitor_id, current_ms)
                if dwell_result:
                    zone_id, dwell_ms = dwell_result
                    seq = session_trk.get_seq(visitor_id)
                    events.append(emit_zone_dwell(
                        camera_id, visitor_id, timestamp,
                        zone_id, dwell_ms, float(conf), is_staff, seq
                    ))

        # ── Lost tracks ────────────────────────────────────────────────────────
        lost_ids = set(active_tracks.keys()) - current_ids
        for track_id in lost_ids:
            visitor_id   = make_visitor_id(track_id, camera_id)
            zone_id      = active_tracks.pop(track_id)
            dwell_result = dwell_trk.exit_zone(visitor_id, current_ms)

            if dwell_result and zone_id:
                zone_id_final, dwell_ms = dwell_result
                seq      = session_trk.get_seq(visitor_id)
                is_staff = staff_det.is_staff(camera_id, track_crops.get(track_id))
                if dwell_ms > 0:
                    events.append(emit_zone_dwell(
                        camera_id, visitor_id, timestamp,
                        zone_id_final, dwell_ms, 0.5, is_staff, seq
                    ))

            if is_billing:
                queue_trk.exit(visitor_id)

    cap.release()
    print(f"✅ {camera_id} done — {len(events)} events generated")
    return events


# ── Main ───────────────────────────────────────────────────────────────────────

def run_detection() -> list[dict]:
    print("🚀 Loading YOLOv8 model...")
    model = YOLO(MODEL_PATH)
    model.to("cuda")

    all_events = []

    for camera_id, config in CAMERA_CONFIG.items():
        events = process_clip(camera_id, config, model)
        all_events.extend(events)

    all_events.sort(key=lambda e: e["timestamp"])

    output_path = EVENTS_DIR / "detected_events.jsonl"
    save_events(all_events, output_path)

    print(f"\n📊 Total events: {len(all_events)}")
    print(f"📁 Saved to: {output_path}")

    return all_events


if __name__ == "__main__":
    run_detection()