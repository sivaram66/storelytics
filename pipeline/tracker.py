import numpy as np
from collections import defaultdict


# ── Visitor ID ─────────────────────────────────────────────────────────────────

def make_visitor_id(track_id: int, camera_id: str) -> str:
    raw   = f"{camera_id}_{track_id}"
    short = hex(abs(hash(raw)) % 0xFFFFFF)[2:].upper().zfill(6)
    return f"VIS_{short}"


# ── Tripwire Direction (kept for compatibility) ────────────────────────────────

class DirectionDetector:
    def __init__(self, entry_direction="down", threshold_px=30):
        self.history        = defaultdict(list)
        self.entry_direction = entry_direction
        self.threshold_px   = threshold_px

    def update(self, track_id: int, cy: float) -> str | None:
        self.history[track_id].append(cy)
        if len(self.history[track_id]) < 5:
            return None
        recent = self.history[track_id][-5:]
        delta  = recent[-1] - recent[0]
        if abs(delta) < self.threshold_px:
            return None
        return "ENTRY" if delta > 0 else "EXIT"

    def clear(self, track_id: int):
        self.history.pop(track_id, None)


# ── Zone Classifier ────────────────────────────────────────────────────────────

class ZoneClassifier:
    ZONE_MAP = {
        "CAM_1": "SKINCARE",
        "CAM_2": "MAKEUP",
        "CAM_3": "ENTRY_THRESHOLD",
        "CAM_4": "STOCKROOM",
        "CAM_5": "BILLING",
    }

    def get_zone(self, camera_id: str, cx: float, cy: float,
                 frame_w: int, frame_h: int) -> str:
        if camera_id == "CAM_2":
            return "MAKEUP" if cx < frame_w * 0.6 else "ACCESSORIES"
        return self.ZONE_MAP.get(camera_id, "UNKNOWN")


# ── Staff Detector ─────────────────────────────────────────────────────────────

class StaffDetector:
    """
    Detects staff using three signals:
    1. Stockroom camera — always staff
    2. Billing camera — always staff (no customers came to billing in our footage)
    3. Dark uniform — all black outfit (brightness threshold)
    """

    STAFF_ONLY_CAMERAS = {"CAM_4", "CAM_5"}  # stockroom + billing = staff only

    def is_staff(self, camera_id: str, crop_rgb: np.ndarray | None = None) -> bool:
        # Camera-based detection first
        if camera_id in self.STAFF_ONLY_CAMERAS:
            return True
        # Clothing color analysis
        if crop_rgb is not None:
            return self._dark_uniform(crop_rgb)
        return False

    def _dark_uniform(self, crop: np.ndarray) -> bool:
        if crop.size == 0:
            return False
        h, w   = crop.shape[:2]
        # Sample middle 60% of crop to avoid background noise
        mid    = crop[int(h*0.2):int(h*0.8), int(w*0.2):int(w*0.8)]
        if mid.size == 0:
            return False
        # Check brightness — Purplle staff wear all black
        avg_brightness = float(np.mean(mid))
        # Check color saturation — black clothing has low saturation
        avg_saturation = float(np.std(mid))
        # Staff: dark AND low color variation
        return avg_brightness < 70 and avg_saturation < 40


# ── Dwell Tracker ──────────────────────────────────────────────────────────────

class DwellTracker:
    def __init__(self, dwell_interval_ms: int = 30_000):
        self.zone_entry:      dict[str, tuple[str, float]] = {}
        self.last_dwell_emit: dict[str, float]             = {}
        self.dwell_interval_ms = dwell_interval_ms

    def enter_zone(self, visitor_id: str, zone_id: str, current_ms: float):
        self.zone_entry[visitor_id]      = (zone_id, current_ms)
        self.last_dwell_emit[visitor_id] = current_ms

    def check_dwell(self, visitor_id: str, current_ms: float) -> tuple | None:
        if visitor_id not in self.zone_entry:
            return None
        zone_id, entry_ms = self.zone_entry[visitor_id]
        since_last        = current_ms - self.last_dwell_emit[visitor_id]
        if since_last >= self.dwell_interval_ms:
            dwell_ms = int(current_ms - entry_ms)
            self.last_dwell_emit[visitor_id] = current_ms
            return zone_id, dwell_ms
        return None

    def exit_zone(self, visitor_id: str, current_ms: float) -> tuple | None:
        if visitor_id not in self.zone_entry:
            return None
        zone_id, entry_ms = self.zone_entry.pop(visitor_id)
        self.last_dwell_emit.pop(visitor_id, None)
        return zone_id, int(current_ms - entry_ms)


# ── Queue Tracker ──────────────────────────────────────────────────────────────

class QueueTracker:
    def __init__(self):
        self.in_billing: set[str] = set()

    def enter(self, visitor_id: str) -> int:
        self.in_billing.add(visitor_id)
        return len(self.in_billing)

    def exit(self, visitor_id: str) -> int:
        self.in_billing.discard(visitor_id)
        return len(self.in_billing)

    @property
    def depth(self) -> int:
        return len(self.in_billing)


# ── Session Tracker ────────────────────────────────────────────────────────────

class SessionTracker:
    def __init__(self):
        self.sessions: dict[str, int] = defaultdict(int)
        self.exited:   set[str]       = set()

    def enter(self, visitor_id: str) -> int:
        if visitor_id in self.exited:
            self.sessions[visitor_id] += 1
        else:
            if visitor_id not in self.sessions:
                self.sessions[visitor_id] = 1
        return self.sessions[visitor_id]

    def exit(self, visitor_id: str):
        self.exited.add(visitor_id)

    def get_seq(self, visitor_id: str) -> int:
        return self.sessions.get(visitor_id, 1)