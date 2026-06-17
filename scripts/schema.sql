CREATE TABLE IF NOT EXISTS cameras (
    camera_id TEXT PRIMARY KEY,
    rtsp_url TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS parking_slots (
    id BIGSERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    slot_id TEXT NOT NULL,
    polygon JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (camera_id, slot_id)
);

CREATE TABLE IF NOT EXISTS occupancy_events (
    id BIGSERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    slot_id TEXT NOT NULL,
    occupied BOOLEAN NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    event_time TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parking_slots_camera_id
    ON parking_slots(camera_id);

CREATE INDEX IF NOT EXISTS idx_occupancy_events_camera_time
    ON occupancy_events(camera_id, event_time DESC);

CREATE INDEX IF NOT EXISTS idx_occupancy_events_camera_slot_time
    ON occupancy_events(camera_id, slot_id, event_time DESC);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cameras_set_updated_at ON cameras;
CREATE TRIGGER cameras_set_updated_at
BEFORE UPDATE ON cameras
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS parking_slots_set_updated_at ON parking_slots;
CREATE TRIGGER parking_slots_set_updated_at
BEFORE UPDATE ON parking_slots
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_occupancy AS
SELECT
    camera_id,
    date_trunc('hour', event_time) AS hour_bucket,
    COUNT(*) FILTER (WHERE occupied) AS occupied_events,
    COUNT(*) AS total_events,
    AVG(CASE WHEN occupied THEN 100.0 ELSE 0.0 END) AS avg_occupancy_pct
FROM occupancy_events
GROUP BY camera_id, date_trunc('hour', event_time)
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_hourly_occupancy_camera_hour
    ON hourly_occupancy(camera_id, hour_bucket);
