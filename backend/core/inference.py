"""Bounded round-robin inference queue.

The shared YOLO model (added earlier in this PR for issue #4) means multiple
camera workers contend for one model instance. Without a coordinator, a
single fast or chatty camera can monopolize the model and starve the rest.

This module provides a tiny scheduler:

* Each camera registers a single-slot frame buffer (drop-oldest: a newer
  frame replaces a pending older one silently).
* One inference worker thread loops over registered cameras round-robin,
  consuming one frame per camera per cycle.
* Submitters never block; processing runs out-of-band on the shared thread.

Net effect: a camera that submits 10x as fast as the others doesn't get
10x the inference budget — it gets the same one-frame-per-round slice.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

Processor = Callable[[Any], None]


class InferenceQueue:
    """Single inference thread, per-camera single-slot drop-oldest buffer."""

    def __init__(self) -> None:
        self._slots: dict[str, Any] = {}
        self._processors: dict[str, Processor] = {}
        self._order: list[str] = []  # stable iteration order for fairness
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rr_index = 0

    # -- registration --------------------------------------------------

    def register(self, camera_id: str, processor: Processor) -> None:
        with self._lock:
            if camera_id not in self._slots:
                self._order.append(camera_id)
            self._slots[camera_id] = None
            self._processors[camera_id] = processor

    def deregister(self, camera_id: str) -> None:
        with self._lock:
            self._slots.pop(camera_id, None)
            self._processors.pop(camera_id, None)
            try:
                self._order.remove(camera_id)
            except ValueError:
                pass

    # -- submission ----------------------------------------------------

    def submit(self, camera_id: str, frame: Any) -> None:
        """Stage a frame for inference. Replaces any pending frame for the
        same camera (drop-oldest, queue depth = 1)."""
        with self._lock:
            if camera_id not in self._slots:
                return
            self._slots[camera_id] = frame
        self._wake.set()

    def pending_count(self) -> int:
        """Total cameras with a pending frame (test/instrumentation only)."""
        with self._lock:
            return sum(1 for v in self._slots.values() if v is not None)

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="inference-queue",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    # -- scheduler -----------------------------------------------------

    def _next_work(self) -> tuple[str, Processor, Any] | None:
        with self._lock:
            n = len(self._order)
            if n == 0:
                return None
            for offset in range(n):
                idx = (self._rr_index + offset) % n
                cid = self._order[idx]
                frame = self._slots.get(cid)
                if frame is not None:
                    self._slots[cid] = None
                    self._rr_index = (idx + 1) % n
                    return cid, self._processors[cid], frame
        return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            work = self._next_work()
            if work is None:
                self._wake.wait(timeout=0.1)
                self._wake.clear()
                continue
            cam_id, processor, frame = work
            try:
                processor(frame)
            except Exception:  # noqa: BLE001 - keep scheduler alive
                logger.exception("inference failed for camera %s", cam_id)
