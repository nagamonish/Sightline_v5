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
            "postgresql://sightline:sightline@postgres:5432/sightline",
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

    async def history(self, camera_id: str, hours: int = 24) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        if self.memory_mode:
            buckets: dict[str, dict[str, int]] = {}
            for event in self._events:
                if event["camera_id"] != camera_id or event["event_time"] < since:
                    continue
                bucket = event["event_time"].replace(
                    minute=0,
                    second=0,
                    microsecond=0,
                ).isoformat()
                stats = buckets.setdefault(bucket, {"occupied": 0, "total": 0})
                stats["total"] += 1
                if event["occupied"]:
                    stats["occupied"] += 1
            return [
                {
                    "bucket": bucket,
                    "occupied": stats["occupied"],
                    "total": stats["total"],
                    "occupancy_pct": round(
                        (stats["occupied"] / stats["total"]) * 100.0,
                        2,
                    )
                    if stats["total"]
                    else 0.0,
                }
                for bucket, stats in sorted(buckets.items())
            ]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT date_trunc('hour', event_time) AS bucket,
                       COUNT(*) FILTER (WHERE occupied) AS occupied,
                       COUNT(*) AS total
                FROM occupancy_events
                WHERE camera_id = $1
                  AND event_time >= now() - ($2::text || ' hours')::interval
                GROUP BY 1
                ORDER BY 1 ASC
                """,
                camera_id,
                hours,
            )

        return [
            {
                "bucket": row["bucket"].isoformat(),
                "occupied": int(row["occupied"]),
                "total": int(row["total"]),
                "occupancy_pct": round(
                    (int(row["occupied"]) / int(row["total"])) * 100.0,
                    2,
                )
                if int(row["total"])
                else 0.0,
            }
            for row in rows
        ]

    async def peak_hours(self, camera_id: str) -> list[dict[str, Any]]:
        if self.memory_mode:
            buckets: dict[int, dict[str, int]] = {}
            for event in self._events:
                if event["camera_id"] != camera_id:
                    continue
                hour = event["event_time"].hour
                stats = buckets.setdefault(hour, {"occupied": 0, "total": 0})
                stats["total"] += 1
                if event["occupied"]:
                    stats["occupied"] += 1
            return [
                {
                    "hour": hour,
                    "occupied_events": stats["occupied"],
                    "avg_occupancy_pct": round(
                        (stats["occupied"] / stats["total"]) * 100.0,
                        2,
                    )
                    if stats["total"]
                    else 0.0,
                }
                for hour, stats in sorted(
                    buckets.items(),
                    key=lambda item: item[1]["occupied"],
                    reverse=True,
                )
            ]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT EXTRACT(HOUR FROM event_time)::int AS hour,
                       COUNT(*) FILTER (WHERE occupied) AS occupied_events,
                       AVG(CASE WHEN occupied THEN 100.0 ELSE 0.0 END) AS avg_occupancy_pct
                FROM occupancy_events
                WHERE camera_id = $1
                GROUP BY 1
                ORDER BY occupied_events DESC, hour ASC
                """,
                camera_id,
            )

        return [
            {
                "hour": int(row["hour"]),
                "occupied_events": int(row["occupied_events"]),
                "avg_occupancy_pct": round(float(row["avg_occupancy_pct"] or 0.0), 2),
            }
            for row in rows
        ]
