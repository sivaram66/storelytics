-- Storelytics — Database Schema
-- This runs automatically when PostgreSQL container starts for the first time

CREATE TABLE IF NOT EXISTS events (
    id            SERIAL PRIMARY KEY,
    event_id      VARCHAR(36)  NOT NULL UNIQUE,
    store_id      VARCHAR(64)  NOT NULL,
    camera_id     VARCHAR(32)  NOT NULL,
    visitor_id    VARCHAR(32)  NOT NULL,
    event_type    VARCHAR(32)  NOT NULL,
    timestamp     TIMESTAMPTZ  NOT NULL,
    zone_id       VARCHAR(32),
    dwell_ms      INTEGER      NOT NULL DEFAULT 0,
    is_staff      BOOLEAN      NOT NULL DEFAULT FALSE,
    confidence    FLOAT        NOT NULL DEFAULT 0.0,
    meta          JSONB        NOT NULL DEFAULT '{}'::jsonb
);

-- Indexes for fast analytics queries
CREATE INDEX IF NOT EXISTS idx_events_store_id    ON events(store_id);
CREATE INDEX IF NOT EXISTS idx_events_visitor_id  ON events(visitor_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp   ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_event_type  ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_store_type  ON events(store_id, event_type);