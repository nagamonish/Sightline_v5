from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np

from backend.core.detector import ParkingDetector
from backend.core.inference import InferenceQueue


logger = logging.getLogger(__name__)

ChangeCallback = Callable[[str, list[dict[str, Any]]], None]


class RTSPStream:
    """Continuously reads RTSP frames without letting downstream work block capture."""

    def __init__(self, camera_id: str, rtsp_url: str, queue_size: int = 4) -> None:
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.frame_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None
        self._latest_frame: np.ndarray | None = None
        self._latest_lock = threading.Lock()
        self.status = "stopped"
        self.last_error: str | None = None
        self.last_frame_at: float | None = None
        self.connected_at: float | None = None
        self.reconnect_attempts = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._reader_loop,
            name=f"rtsp-reader-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self.status = "stopped"
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._release_capture()
        self._clear_queue()

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def latest_frame(self) -> np.ndarray | None:
        with self._latest_lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def _reader_loop(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            self.status = "reconnecting" if self.reconnect_attempts else "connecting"
            capture = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            if not capture.isOpened():
                self.last_error = "unable to open RTSP stream"
                self.reconnect_attempts += 1
                self._sleep_backoff(backoff)
                backoff = min(backoff * 2, 60.0)
                continue

            self._capture = capture
            self.status = "connected"
            self.connected_at = time.time()
            self.last_error = None
            self.reconnect_attempts = 0
            backoff = 1.0

            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    self.last_error = "frame read failed"
                    self.status = "reconnecting"
                    break

                self.last_frame_at = time.time()
                with self._latest_lock:
                    self._latest_frame = frame.copy()

                self._push_frame(frame)

            self._release_capture()
            if not self._stop_event.is_set():
                self.reconnect_attempts += 1
                self._sleep_backoff(backoff)
                backoff = min(backoff * 2, 60.0)

    def _push_frame(self, frame: np.ndarray) -> None:
        while self.frame_queue.full():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        try:
            self.frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    def _sleep_backoff(self, seconds: float) -> None:
        self.status = "reconnecting"
        self._stop_event.wait(seconds)

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _clear_queue(self) -> None:
        while True:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                return


@dataclass
class CameraWorker:
    camera_id: str
    name: str
    rtsp_url: str
    slots: list[dict[str, Any]] = field(default_factory=list)
    model_path: str | None = None
    on_change: ChangeCallback | None = None
    inference_queue: InferenceQueue | None = None

    def __post_init__(self) -> None:
        self.stream = RTSPStream(self.camera_id, self.rtsp_url)
        self.detector = ParkingDetector(self.camera_id, self.model_path)
        self.detector.load_slots(self.slots)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._annotated_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self.processed_frames = 0
        self.last_processed_at: float | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        self.stream.start()
        # Register with the shared inference scheduler so frames flow through
        # one fair round-robin queue instead of N independent contending threads.
        if self.inference_queue is not None:
            self.inference_queue.register(self.camera_id, self._process_inference_frame)
            self.inference_queue.start()  # idempotent if already running
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._reader_loop if self.inference_queue is not None else self._detect_loop,
            name=f"reader-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self.inference_queue is not None:
            self.inference_queue.deregister(self.camera_id)
        self.stream.stop()

    @property
    def status(self) -> str:
        if self.last_error:
            return "error"
        return self.stream.status

    def update_slots(self, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.detector.load_slots(slots)
        return self.detector.get_slots()

    def set_homography(
        self,
        src_points: list[list[float]],
        dst_points: list[list[float]],
    ) -> list[list[float]]:
        matrix = self.detector.set_homography(src_points, dst_points)
        return matrix.tolist()

    def latest_frame(self) -> np.ndarray | None:
        with self._frame_lock:
            if self._annotated_frame is not None:
                return self._annotated_frame.copy()
        return self.stream.latest_frame()

    def latest_jpeg(self, quality: int = 82) -> bytes | None:
        frame = self.latest_frame()
        if frame is None:
            return None
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)],
        )
        if not ok:
            return None
        return encoded.tobytes()

    def snapshot_for_calibration(self) -> np.ndarray | None:
        return self.stream.latest_frame()

    def summary(self) -> dict[str, Any]:
        slots = self.detector.get_slots()
        occupied = sum(1 for slot in slots if slot["occupied"])
        total = len(slots)
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "status": self.status,
            "total": total,
            "occupied": occupied,
            "available": total - occupied,
            "occupancy_pct": round((occupied / total) * 100.0, 2) if total else 0.0,
            "last_frame_at": self.stream.last_frame_at,
            "last_processed_at": self.last_processed_at,
            "reconnect_attempts": self.stream.reconnect_attempts,
            "last_error": self.last_error or self.stream.last_error,
        }

    def _reader_loop(self) -> None:
        """Used when an InferenceQueue is attached. Reads frames and hands them
        off to the shared scheduler — never runs the detector inline."""
        assert self.inference_queue is not None
        while not self._stop_event.is_set():
            frame = self.stream.read(timeout=0.5)
            if frame is None:
                continue
            # Drop-oldest behavior is enforced by the queue.
            self.inference_queue.submit(self.camera_id, frame)

    def _process_inference_frame(self, frame: np.ndarray) -> None:
        """Called by the shared InferenceQueue worker thread."""
        try:
            changed_slots, annotated = self.detector.process_frame(frame)
            with self._frame_lock:
                self._annotated_frame = annotated
            self.processed_frames += 1
            self.last_processed_at = time.time()
            self.last_error = None
            if changed_slots and self.on_change is not None:
                self.on_change(self.camera_id, changed_slots)
        except Exception as exc:  # noqa: BLE001 - keep scheduler alive
            self.last_error = str(exc)
            logger.exception("camera %s detection failed", self.camera_id)

    def _detect_loop(self) -> None:
        """Fallback path used when no InferenceQueue is attached. Kept for
        backward compatibility with callers that build CameraWorker directly."""
        while not self._stop_event.is_set():
            frame = self.stream.read(timeout=0.5)
            if frame is None:
                continue

            try:
                changed_slots, annotated = self.detector.process_frame(frame)
                with self._frame_lock:
                    self._annotated_frame = annotated
                self.processed_frames += 1
                self.last_processed_at = time.time()
                self.last_error = None

                if changed_slots and self.on_change is not None:
                    self.on_change(self.camera_id, changed_slots)
            except Exception as exc:  # noqa: BLE001 - keep camera loop alive.
                self.last_error = str(exc)
                logger.exception("camera %s detection failed", self.camera_id)
                time.sleep(0.2)


class CameraManager:
    def __init__(
        self,
        model_path: str | None = None,
        on_change: ChangeCallback | None = None,
    ) -> None:
        self.model_path = model_path
        self.on_change = on_change
        self._workers: dict[str, CameraWorker] = {}
        self._lock = threading.RLock()
        # One scheduler shared across every camera owned by this manager. It
        # services cameras round-robin so a single chatty camera can't lock
        # the shared YOLO model and starve the rest.
        self.inference_queue = InferenceQueue()

    def add_camera(
        self,
        camera_id: str,
        rtsp_url: str,
        name: str | None = None,
        slots: list[dict[str, Any]] | None = None,
        start: bool = True,
    ) -> CameraWorker:
        with self._lock:
            if camera_id in self._workers:
                self._workers[camera_id].stop()

            worker = CameraWorker(
                camera_id=camera_id,
                name=name or camera_id,
                rtsp_url=rtsp_url,
                slots=slots or [],
                model_path=self.model_path,
                on_change=self.on_change,
                inference_queue=self.inference_queue,
            )
            self._workers[camera_id] = worker
            if start:
                worker.start()
            return worker

    def remove_camera(self, camera_id: str) -> bool:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker is None:
            return False
        worker.stop()
        return True

    def stop_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop()

    def get_worker(self, camera_id: str) -> CameraWorker | None:
        with self._lock:
            return self._workers.get(camera_id)

    def list_cameras(self) -> list[dict[str, Any]]:
        with self._lock:
            workers = list(self._workers.values())
        return [worker.summary() for worker in workers]

    def get_slots(self, camera_id: str) -> list[dict[str, Any]] | None:
        worker = self.get_worker(camera_id)
        if worker is None:
            return None
        return worker.detector.get_slots()

    def update_slots(self, camera_id: str, slots: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        worker = self.get_worker(camera_id)
        if worker is None:
            return None
        return worker.update_slots(slots)

    def set_homography(
        self,
        camera_id: str,
        src_points: list[list[float]],
        dst_points: list[list[float]],
    ) -> list[list[float]] | None:
        worker = self.get_worker(camera_id)
        if worker is None:
            return None
        return worker.set_homography(src_points, dst_points)

    def state(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            items = list(self._workers.items())
        return {
            camera_id: worker.detector.get_slots()
            for camera_id, worker in items
        }
