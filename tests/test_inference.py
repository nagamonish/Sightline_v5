"""Tests for the bounded round-robin inference queue (issue #4 follow-up)."""
from __future__ import annotations

import threading
import time

import pytest

from backend.core.inference import InferenceQueue


@pytest.fixture
def queue():
    q = InferenceQueue()
    q.start()
    yield q
    q.stop()


def _make_processor(counter: dict[str, int], camera_id: str, delay: float = 0.0):
    """A processor that just counts how many times it was called."""

    def process(_frame):
        if delay:
            time.sleep(delay)
        counter[camera_id] = counter.get(camera_id, 0) + 1

    return process


def test_drop_oldest_when_camera_submits_faster_than_consumer_can_drain(queue):
    """Hammering submit() must never let the pending count exceed one frame
    per camera — older frames are dropped silently."""
    seen: dict[str, int] = {}
    # Slow processor so we can observe the queue depth.
    queue.register("cam_slow", _make_processor(seen, "cam_slow", delay=0.05))

    for i in range(50):
        queue.submit("cam_slow", f"frame-{i}")
        # Even mid-flood, depth never exceeds 1 because we drop-oldest.
        assert queue.pending_count() <= 1

    # Drain.
    time.sleep(0.4)
    # The slow consumer ran a handful of times; the rest of the 50 frames
    # were dropped on the floor by the bounded slot. This is the point.
    assert seen["cam_slow"] >= 1
    assert seen["cam_slow"] <= 50


def test_flooding_one_camera_does_not_starve_others():
    """The regression test for the issue: a chatty camera must not prevent
    other cameras from getting inference time."""
    seen: dict[str, int] = {}
    q = InferenceQueue()
    q.register("flooder", _make_processor(seen, "flooder", delay=0.005))
    q.register("victim_a", _make_processor(seen, "victim_a", delay=0.005))
    q.register("victim_b", _make_processor(seen, "victim_b", delay=0.005))
    q.start()

    stop = threading.Event()

    def flood():
        while not stop.is_set():
            q.submit("flooder", "f")

    flood_thread = threading.Thread(target=flood, daemon=True)
    flood_thread.start()

    # Send a small, paced stream to each victim so the scheduler has work to
    # round-robin between.
    for _ in range(15):
        q.submit("victim_a", "a")
        q.submit("victim_b", "b")
        time.sleep(0.02)

    stop.set()
    flood_thread.join(timeout=1.0)
    # Let the queue drain.
    time.sleep(0.2)
    q.stop()

    # Both victims must have been processed *at least* a meaningful share —
    # if the flooder had monopolized the scheduler, these would be near zero.
    assert seen.get("victim_a", 0) >= 5, (
        f"victim_a was starved by the flooder: seen={seen}"
    )
    assert seen.get("victim_b", 0) >= 5, (
        f"victim_b was starved by the flooder: seen={seen}"
    )


def test_deregister_stops_a_camera_from_being_serviced():
    seen: dict[str, int] = {}
    q = InferenceQueue()
    q.register("cam1", _make_processor(seen, "cam1"))
    q.register("cam2", _make_processor(seen, "cam2"))
    q.start()

    q.submit("cam1", "x")
    q.submit("cam2", "y")
    time.sleep(0.1)
    assert seen.get("cam1", 0) == 1
    assert seen.get("cam2", 0) == 1

    q.deregister("cam1")
    q.submit("cam1", "x2")  # silently dropped — cam1 no longer registered
    q.submit("cam2", "y2")
    time.sleep(0.1)
    assert seen.get("cam1", 0) == 1  # unchanged
    assert seen.get("cam2", 0) == 2
    q.stop()
