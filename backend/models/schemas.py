from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


Point = list[float]
Polygon = list[Point]


class SlotCreate(BaseModel):
    slot_id: str
    polygon: Polygon


class SlotState(SlotCreate):
    occupied: bool = False
    confidence: float = 1.0
    last_changed: float | None = None
    occupied_since: float | None = None


class CameraCreate(BaseModel):
    camera_id: str = Field(..., min_length=1)
    rtsp_url: str = Field(..., min_length=1)
    name: str | None = None
    slots: list[SlotCreate] = Field(default_factory=list)


class SlotUpdate(BaseModel):
    slots: list[SlotCreate]


class HomographyRequest(BaseModel):
    src_points: list[Point] = Field(..., min_length=4, max_length=4)
    dst_points: list[Point] = Field(..., min_length=4, max_length=4)


class CameraSummary(BaseModel):
    camera_id: str
    name: str
    status: str
    total: int
    occupied: int
    available: int
    occupancy_pct: float
    last_frame_at: float | None = None
    last_processed_at: float | None = None
    reconnect_attempts: int = 0
    last_error: str | None = None


class AnalyticsPoint(BaseModel):
    bucket: str
    occupied: int
    total: int
    occupancy_pct: float


class PeakHour(BaseModel):
    hour: int
    occupied_events: int
    avg_occupancy_pct: float | None = None


class WebSocketEnvelope(BaseModel):
    type: str
    cameras: dict[str, list[dict[str, Any]]] | None = None
    camera_id: str | None = None
    slots: list[dict[str, Any]] | None = None
    summary: list[dict[str, Any]]
