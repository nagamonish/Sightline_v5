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

-- Time-weighted hourly occupancy. The previous version of this view counted
-- *events* per bucket; a slot occupied for five hours without state changes
-- contributed only one row. This version derives (start, end] state intervals
-- per slot from consecutive events (LEAD), splits each interval at hour
-- boundaries with generate_series, and sums the seconds in each bucket.
-- occupancy_pct is the time-weighted ratio occupied_seconds / total_seconds.
DROP MATERIALIZED VIEW IF EXISTS hourly_occupancy;

CREATE MATERIALIZED VIEW hourly_occupancy AS
WITH events AS (
    SELECT
        camera_id,
        slot_id,
        occupied,
        event_time,
        LEAD(event_time, 1, now()) OVER (
            PARTITION BY camera_id, slot_id ORDER BY event_time
        ) AS next_time
    FROM occupancy_events
),
bucketed AS (
    SELECT
        e.camera_id,
        bucket,
        e.occupied,
        e.event_time,
        e.next_time
    FROM events e
    CROSS JOIN LATERAL generate_series(
        date_trunc('hour', e.event_time),
        date_trunc('hour', e.next_time),
        interval '1 hour'
    ) AS bucket
),
durations AS (
    SELECT
        camera_id,
        bucket AS hour_bucket,
        occupied,
        GREATEST(
            EXTRACT(EPOCH FROM (
                LEAST(next_time, bucket + interval '1 hour')
                - GREATEST(event_time, bucket)
            )),
            0
        ) AS seconds_in_bucket
    FROM bucketed
)
SELECT
    camera_id,
    hour_bucket,
    SUM(CASE WHEN occupied THEN seconds_in_bucket ELSE 0 END) AS occupied_seconds,
    SUM(seconds_in_bucket) AS total_seconds,
    CASE
        WHEN SUM(seconds_in_bucket) > 0
            THEN ROUND(
                (SUM(CASE WHEN occupied THEN seconds_in_bucket ELSE 0 END)
                    * 100.0 / SUM(seconds_in_bucket))::numeric,
                2
            )
        ELSE 0.0
    END AS occupancy_pct
FROM durations
GROUP BY camera_id, hour_bucket
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_hourly_occupancy_camera_hour
    ON hourly_occupancy(camera_id, hour_bucket);
