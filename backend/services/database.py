from __future__ import annotations

import logging
import os
import json
from datetime import UTC, datetime, timedelta
from typing import Any

try:
    import asyncpg
except ImportError:  # pragma: no cover - exercised only in minimal local envs.
    asyncpg = None


logger = logging.getLogger(__name__)


class Database:
    """PostgreSQL CRUD with an in-memory fallback for local UI/demo runs."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://parkiq:parkiq@postgres:5432/parkiq",
        )
        self.pool: Any = None
        self.memory_mode = False
        self._cameras: dict[str, dict[str, Any]] = {}
        self._slots: dict[str, list[dict[str, Any]]] = {}
        self._events: list[dict[str, Any]] = []

    async def connect(self) -> None:
        if asyncpg is None:
            self.memory_mode = True
            logger.warning("asyncpg unavailable; using in-memory persistence")
            return

        try:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=8,
                command_timeout=30,
            )
            self.memory_mode = False
        except Exception:  # noqa: BLE001 - allow app to boot for camera/UI work.
            self.memory_mode = True
            logger.exception("database unavailable; using in-memory persistence")

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def upsert_camera(self, camera_id: str, rtsp_url: str, name: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        if self.memory_mode:
            record = {
                "camera_id": camera_id,
                "rtsp_url": rtsp_url,
                "name": name,
                "created_at": self._cameras.get(camera_id, {}).get("created_at", now),
                "updated_at": now,
            }
            self._cameras[camera_id] = record
            return record

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO cameras (camera_id, rtsp_url, name)
                VALUES ($1, $2, $3)
                ON CONFLICT (camera_id)
                DO UPDATE SET rtsp_url = EXCLUDED.rtsp_url,
                              name = EXCLUDED.name,
                              updated_at = now()
                RETURNING camera_id, rtsp_url, name, created_at, updated_at
                """,
                camera_id,
                rtsp_url,
                name,
            )
        return dict(row)

    async def delete_camera(self, camera_id: str) -> bool:
        if self.memory_mode:
            existed = camera_id in self._cameras
            self._cameras.pop(camera_id, None)
            self._slots.pop(camera_id, None)
            self._events = [
                event for event in self._events if event["camera_id"] != camera_id
            ]
            return existed

        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM cameras WHERE camera_id = $1",
                camera_id,
            )
        return result.endswith("1")

    async def list_cameras(self) -> list[dict[str, Any]]:
        if self.memory_mode:
            return [dict(camera) for camera in self._cameras.values()]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT camera_id, rtsp_url, name, created_at, updated_at
                FROM cameras
                ORDER BY created_at ASC
                """
            )
        return [dict(row) for row in rows]

    async def get_camera(self, camera_id: str) -> dict[str, Any] | None:
        if self.memory_mode:
            camera = self._cameras.get(camera_id)
            return dict(camera) if camera else None

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT camera_id, rtsp_url, name, created_at, updated_at
                FROM cameras
                WHERE camera_id = $1
                """,
                camera_id,
            )
        return dict(row) if row else None

    async def replace_slots(
        self,
        camera_id: str,
        slots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.memory_mode:
            serialized = [
                {
                    "slot_id": slot["slot_id"],
                    "polygon": slot["polygon"],
                    "occupied": bool(slot.get("occupied", False)),
                    "confidence": float(slot.get("confidence", 1.0)),
                    "last_changed": slot.get("last_changed"),
                    "occupied_since": slot.get("occupied_since"),
                }
                for slot in slots
            ]
            self._slots[camera_id] = serialized
            return serialized

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM parking_slots WHERE camera_id = $1",
                    camera_id,
                )
                for slot in slots:
                    await conn.execute(
                        """
                        INSERT INTO parking_slots (camera_id, slot_id, polygon)
                        VALUES ($1, $2, $3::jsonb)
                        """,
                        camera_id,
                        slot["slot_id"],
                        json.dumps(slot["polygon"]),
                    )
        return await self.get_slots(camera_id)

    async def get_slots(self, camera_id: str) -> list[dict[str, Any]]:
        if self.memory_mode:
            return [dict(slot) for slot in self._slots.get(camera_id, [])]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT slot_id, polygon
                FROM parking_slots
                WHERE camera_id = $1
                ORDER BY slot_id ASC
                """,
                camera_id,
            )
        return [
            {
                "slot_id": row["slot_id"],
                "polygon": json.loads(row["polygon"]) if isinstance(row["polygon"], str) else row["polygon"],
                "occupied": False,
                "confidence": 1.0,
                "last_changed": None,
                "occupied_since": None,
            }
            for row in rows
        ]

    async def insert_event(
        self,
        camera_id: str,
        slot: dict[str, Any],
    ) -> None:
        event_time = slot.get("last_changed")
        if isinstance(event_time, (int, float)):
            event_time = datetime.fromtimestamp(event_time, UTC)
        elif event_time is None:
            event_time = datetime.now(UTC)

        record = {
            "camera_id": camera_id,
            "slot_id": slot["slot_id"],
            "occupied": bool(slot["occupied"]),
            "confidence": float(slot.get("confidence", 1.0)),
            "event_time": event_time,
        }

        if self.memory_mode:
            self._events.append(record)
            return

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO occupancy_events
                    (camera_id, slot_id, occupied, confidence, event_time)
                VALUES ($1, $2, $3, $4, $5)
                """,
                record["camera_id"],
                record["slot_id"],
                record["occupied"],
                record["confidence"],
                record["event_time"],
            )

    # ------------------------------------------------------------------
    # Analytics — time-weighted, not event-counted.
    #
    # The old implementations bucketed by event count, so a slot that was
    # occupied for five hours but never changed state during that period
    # contributed only one "occupied event" to history and zero contribution
    # to anything else. The implementations below derive (start, end] state
    # intervals per slot using consecutive events (current event_time ->
    # next event_time for that slot, capped at now() for the last open
    # interval), split each interval at hour boundaries, and sum seconds
    # per bucket. The reported occupancy_pct is the time-weighted ratio
    # occupied_seconds / total_seconds per bucket.
    # ------------------------------------------------------------------

    def _memory_intervals(
        self, camera_id: str, since: datetime | None
    ) -> list[dict[str, Any]]:
        """Group memory-mode events into per-slot (start, end] intervals."""
        now = datetime.now(UTC)
        by_slot: dict[str, list[dict[str, Any]]] = {}
        for event in self._events:
            if event["camera_id"] != camera_id:
                continue
            by_slot.setdefault(event["slot_id"], []).append(event)

        intervals: list[dict[str, Any]] = []
        for slot_events in by_slot.values():
            ordered = sorted(slot_events, key=lambda e: e["event_time"])
            for index, event in enumerate(ordered):
                start: datetime = event["event_time"]
                end = ordered[index + 1]["event_time"] if index + 1 < len(ordered) else now
                if since is not None and end <= since:
                    continue
                if since is not None and start < since:
                    start = since
                if end <= start:
                    continue
                intervals.append(
                    {"start": start, "end": end, "occupied": bool(event["occupied"])}
                )
        return intervals

    @staticmethod
    def _accumulate_seconds(
        intervals: list[dict[str, Any]],
        bucket_key,  # callable: datetime -> hashable
    ) -> dict[Any, dict[str, float]]:
        """Split intervals at hour boundaries and sum seconds per bucket."""
        buckets: dict[Any, dict[str, float]] = {}
        hour = timedelta(hours=1)
        for interval in intervals:
            cursor: datetime = interval["start"]
            end: datetime = interval["end"]
            while cursor < end:
                hour_start = cursor.replace(minute=0, second=0, microsecond=0)
                hour_end = hour_start + hour
                chunk_end = min(end, hour_end)
                seconds = (chunk_end - cursor).total_seconds()
                if seconds > 0:
                    key = bucket_key(hour_start)
                    bucket = buckets.setdefault(
                        key, {"occupied_seconds": 0.0, "total_seconds": 0.0}
                    )
                    bucket["total_seconds"] += seconds
                    if interval["occupied"]:
                        bucket["occupied_seconds"] += seconds
                cursor = chunk_end
        return buckets

    async def history(self, camera_id: str, hours: int = 24) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        if self.memory_mode:
            intervals = self._memory_intervals(camera_id, since)
            buckets = self._accumulate_seconds(intervals, bucket_key=lambda dt: dt.isoformat())
            return [
                {
                    "bucket": bucket,
                    "occupied_seconds": round(stats["occupied_seconds"], 2),
                    "total_seconds": round(stats["total_seconds"], 2),
                    "occupancy_pct": round(
                        (stats["occupied_seconds"] / stats["total_seconds"]) * 100.0,
                        2,
                    )
                    if stats["total_seconds"]
                    else 0.0,
                }
                for bucket, stats in sorted(buckets.items())
            ]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH events AS (
                    SELECT
                        slot_id,
                        occupied,
                        event_time,
                        LEAD(event_time, 1, now()) OVER (
                            PARTITION BY camera_id, slot_id ORDER BY event_time
                        ) AS next_time
                    FROM occupancy_events
                    WHERE camera_id = $1
                ),
                bucketed AS (
                    SELECT
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
                    WHERE e.next_time > now() - make_interval(hours => $2)
                ),
                durations AS (
                    SELECT
                        bucket,
                        occupied,
                        GREATEST(
                            EXTRACT(EPOCH FROM (
                                LEAST(next_time, bucket + interval '1 hour')
                                - GREATEST(event_time, bucket)
                            )),
                            0
                        ) AS seconds_in_bucket
                    FROM bucketed
                    WHERE bucket >= date_trunc('hour', now() - make_interval(hours => $2))
                )
                SELECT
                    bucket,
                    SUM(CASE WHEN occupied THEN seconds_in_bucket ELSE 0 END) AS occupied_seconds,
                    SUM(seconds_in_bucket) AS total_seconds
                FROM durations
                GROUP BY bucket
                ORDER BY bucket ASC
                """,
                camera_id,
                hours,
            )

        return [
            {
                "bucket": row["bucket"].isoformat(),
                "occupied_seconds": round(float(row["occupied_seconds"] or 0.0), 2),
                "total_seconds": round(float(row["total_seconds"] or 0.0), 2),
                "occupancy_pct": round(
                    float(row["occupied_seconds"] or 0.0)
                    / float(row["total_seconds"]) * 100.0,
                    2,
                )
                if row["total_seconds"]
                else 0.0,
            }
            for row in rows
        ]

    async def peak_hours(self, camera_id: str) -> list[dict[str, Any]]:
        if self.memory_mode:
            intervals = self._memory_intervals(camera_id, since=None)
            buckets = self._accumulate_seconds(intervals, bucket_key=lambda dt: dt.hour)
            return sorted(
                (
                    {
                        "hour": hour,
                        "occupied_seconds": round(stats["occupied_seconds"], 2),
                        "total_seconds": round(stats["total_seconds"], 2),
                        "avg_occupancy_pct": round(
                            (stats["occupied_seconds"] / stats["total_seconds"]) * 100.0,
                            2,
                        )
                        if stats["total_seconds"]
                        else 0.0,
                    }
                    for hour, stats in buckets.items()
                ),
                key=lambda item: (-item["occupied_seconds"], item["hour"]),
            )

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH events AS (
                    SELECT
                        slot_id,
                        occupied,
                        event_time,
                        LEAD(event_time, 1, now()) OVER (
                            PARTITION BY camera_id, slot_id ORDER BY event_time
                        ) AS next_time
                    FROM occupancy_events
                    WHERE camera_id = $1
                ),
                bucketed AS (
                    SELECT
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
                        -- Extract HOUR in UTC so the result is timezone-independent
                        -- and matches the memory-mode path.
                        EXTRACT(HOUR FROM (bucket AT TIME ZONE 'UTC'))::int AS hour,
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
                    hour,
                    SUM(CASE WHEN occupied THEN seconds_in_bucket ELSE 0 END) AS occupied_seconds,
                    SUM(seconds_in_bucket) AS total_seconds
                FROM durations
                GROUP BY hour
                ORDER BY occupied_seconds DESC, hour ASC
                """,
                camera_id,
            )

        return [
            {
                "hour": int(row["hour"]),
                "occupied_seconds": round(float(row["occupied_seconds"] or 0.0), 2),
                "total_seconds": round(float(row["total_seconds"] or 0.0), 2),
                "avg_occupancy_pct": round(
                    float(row["occupied_seconds"] or 0.0)
                    / float(row["total_seconds"]) * 100.0,
                    2,
                )
                if row["total_seconds"]
                else 0.0,
            }
            for row in rows
        ]
