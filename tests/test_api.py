"""Regression tests for the API routes.

Kept light on infrastructure: we drive the FastAPI route functions directly
via asyncio.run and stub out the camera_manager + websocket pieces so the
tests don't depend on real RTSP or a running event loop.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.api import main as api_main
from backend.models.schemas import CameraCreate, SlotCreate
from backend.services.database import Database


def _square(slot_id: str) -> SlotCreate:
    return SlotCreate(slot_id=slot_id, polygon=[[0, 0], [2, 0], [2, 4], [0, 4]])


class _StubWorker:
    """Minimal stand-in for CameraWorker so add_camera's return path works."""

    def __init__(self, camera_id: str, slots: list[dict]) -> None:
        self._camera_id = camera_id
        self.detector = SimpleNamespace(get_slots=lambda: slots)

    def summary(self) -> dict:
        return {"camera_id": self._camera_id, "status": "starting", "name": self._camera_id}


@pytest.fixture
def patched_api(monkeypatch):
    """Swap in a memory-mode DB and no-op camera/websocket wiring."""
    db = Database(database_url="memory")
    asyncio.run(db.connect())
    monkeypatch.setattr(api_main, "database", db)

    captured_slots: dict[str, list[dict]] = {}

    def stub_add_camera(*, camera_id, slots, **_kwargs):
        captured_slots[camera_id] = list(slots)
        return _StubWorker(camera_id, slots)

    def stub_update_slots(camera_id, slots):
        captured_slots[camera_id] = list(slots)
        return slots

    monkeypatch.setattr(api_main.camera_manager, "add_camera", stub_add_camera)
    monkeypatch.setattr(api_main.camera_manager, "update_slots", stub_update_slots)
    monkeypatch.setattr(api_main.camera_manager, "state", lambda: {})
    monkeypatch.setattr(api_main.camera_manager, "list_cameras", lambda: [])

    async def _broadcast(_msg):
        return None

    monkeypatch.setattr(api_main.websocket_hub, "broadcast", _broadcast)

    return SimpleNamespace(db=db, captured_slots=captured_slots)


def test_post_cameras_with_slots_persists_them(patched_api):
    """Baseline: when slots are submitted, they replace what's stored."""
    asyncio.run(
        api_main.add_camera(
            CameraCreate(
                camera_id="cam1",
                rtsp_url="rtsp://test/feed",
                slots=[_square("A1"), _square("A2")],
            )
        )
    )

    stored = asyncio.run(patched_api.db.get_slots("cam1"))
    assert {s["slot_id"] for s in stored} == {"A1", "A2"}


def test_post_cameras_empty_slots_preserves_existing(patched_api):
    """Re-adding a camera with slots=[] must NOT wipe the calibrated lot."""
    # Calibrate the camera with two slots.
    asyncio.run(
        api_main.add_camera(
            CameraCreate(
                camera_id="cam1",
                rtsp_url="rtsp://test/feed",
                slots=[_square("A1"), _square("A2")],
            )
        )
    )
    assert len(asyncio.run(patched_api.db.get_slots("cam1"))) == 2

    # Simulate the frontend re-adding the same camera while testing — sends an
    # empty slot list. Before the fix this nuked the calibrated lot.
    asyncio.run(
        api_main.add_camera(
            CameraCreate(
                camera_id="cam1",
                rtsp_url="rtsp://test/feed",
                slots=[],
            )
        )
    )

    preserved = asyncio.run(patched_api.db.get_slots("cam1"))
    assert {s["slot_id"] for s in preserved} == {"A1", "A2"}, (
        "POST /cameras with empty slots must preserve the previously calibrated lot"
    )


def test_post_cameras_omitted_slots_preserves_existing(patched_api):
    """Same as above but with the `slots` field completely omitted from the payload."""
    asyncio.run(
        api_main.add_camera(
            CameraCreate(
                camera_id="cam1",
                rtsp_url="rtsp://test/feed",
                slots=[_square("A1")],
            )
        )
    )

    # Build a CameraCreate without ever setting `slots` — distinct from passing [].
    asyncio.run(
        api_main.add_camera(
            CameraCreate(camera_id="cam1", rtsp_url="rtsp://test/feed-new")
        )
    )

    preserved = asyncio.run(patched_api.db.get_slots("cam1"))
    assert [s["slot_id"] for s in preserved] == ["A1"]
