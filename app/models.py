from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from datetime import datetime
from uuid import uuid4


# ── Event Types ────────────────────────────────────────────────────────────────

EventType = Literal[
    "ENTRY",
    "EXIT",
    "ZONE_ENTER",
    "ZONE_EXIT",
    "ZONE_DWELL",
    "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON",
    "REENTRY",
]


# ── Event Metadata ─────────────────────────────────────────────────────────────

class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone:    Optional[str] = None
    session_seq: Optional[int] = None


# ── Core Event Schema ──────────────────────────────────────────────────────────

class StoreEvent(BaseModel):
    event_id:   str      = Field(default_factory=lambda: str(uuid4()))
    store_id:   str
    camera_id:  str
    visitor_id: str
    event_type: EventType
    timestamp:  datetime
    zone_id:    Optional[str]  = None
    dwell_ms:   int            = 0
    is_staff:   bool           = False
    confidence: float          = Field(ge=0.0, le=1.0)
    metadata:   EventMetadata  = Field(default_factory=EventMetadata)

    @field_validator("event_id")
    @classmethod
    def event_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event_id cannot be empty")
        return v


# ── Ingest ─────────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    events: list[StoreEvent] = Field(max_length=500)

class IngestResponse(BaseModel):
    accepted:   int
    duplicates: int
    rejected:   int
    errors:     list[dict] = []


# ── Metrics ────────────────────────────────────────────────────────────────────

class ZoneDwell(BaseModel):
    zone_id:      str
    avg_dwell_ms: float
    visit_count:  int

class MetricsResponse(BaseModel):
    store_id:         str
    unique_visitors:  int
    conversion_rate:  float
    avg_dwell_ms:     float
    zone_dwells:      list[ZoneDwell]
    queue_depth:      int
    abandonment_rate: float
    as_of:            datetime


# ── Funnel ─────────────────────────────────────────────────────────────────────

class FunnelStage(BaseModel):
    stage:       str
    count:       int
    dropoff_pct: float

class FunnelResponse(BaseModel):
    store_id: str
    stages:   list[FunnelStage]
    as_of:    datetime


# ── Heatmap ────────────────────────────────────────────────────────────────────

class HeatmapZone(BaseModel):
    zone_id:         str
    visit_frequency: float
    avg_dwell_ms:    float
    data_confidence: bool

class HeatmapResponse(BaseModel):
    store_id: str
    zones:    list[HeatmapZone]
    as_of:    datetime


# ── Anomalies ──────────────────────────────────────────────────────────────────

AnomalySeverity = Literal["INFO", "WARN", "CRITICAL"]

class Anomaly(BaseModel):
    anomaly_type:     str
    severity:         AnomalySeverity
    description:      str
    suggested_action: str
    detected_at:      datetime

class AnomalyResponse(BaseModel):
    store_id:  str
    anomalies: list[Anomaly]
    as_of:     datetime


# ── Health ─────────────────────────────────────────────────────────────────────

class StoreFeedStatus(BaseModel):
    store_id:           str
    last_event_at:      Optional[datetime]
    stale:              bool
    minutes_since_last: Optional[float]

class HealthResponse(BaseModel):
    status:      Literal["ok", "degraded"]
    store_feeds: list[StoreFeedStatus]
    checked_at:  datetime