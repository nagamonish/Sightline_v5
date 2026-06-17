from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import cv2
import numpy as np


VEHICLE_CLASSES: dict[int, str] = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

VEHICLE_CLASS_NAMES = {
    "car",
    "motorcycle",
    "bus",
    "truck",
    "vehicle",
    "small vehicle",
    "small-vehicle",
    "large vehicle",
    "large-vehicle",
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# Shared YOLO model cache. Each ParkingDetector used to load its own YOLO
# instance, so 10 cameras loaded the model 10 times — slow startup and 10x
# the GPU/CPU memory. This cache keys by model path so any number of
# detectors pointing at the same checkpoint share one loaded model object.
_model_cache: dict[str, Any] = {}
_model_cache_lock = threading.Lock()


def _get_shared_yolo(model_path: str) -> Any:
    """Return the YOLO instance for `model_path`, loading on first request."""
    with _model_cache_lock:
        cached = _model_cache.get(model_path)
        if cached is None:
            from ultralytics import YOLO  # imported lazily so unit tests can stub

            cached = YOLO(model_path)
            _model_cache[model_path] = cached
        return cached


def _to_numpy(value: Any) -> np.ndarray:
    if value is None:
        return np.array([])
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def normalize_polygon(points: Iterable[Iterable[float]]) -> np.ndarray:
    polygon = np.asarray(points, dtype=np.float32)
    if polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3:
        raise ValueError("polygon must be an N x 2 array with at least 3 points")

    if np.allclose(polygon[0], polygon[-1]):
        polygon = polygon[:-1]

    if not np.isfinite(polygon).all():
        raise ValueError("polygon contains non-finite coordinates")

    return polygon.astype(np.float32)


def signed_polygon_area(polygon: np.ndarray) -> float:
    polygon = normalize_polygon(polygon)
    x = polygon[:, 0]
    y = polygon[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - y * np.roll(x, -1)))


def polygon_area(polygon: np.ndarray) -> float:
    if len(polygon) < 3:
        return 0.0
    return abs(signed_polygon_area(polygon))


def _line_intersection(
    start: np.ndarray,
    end: np.ndarray,
    clip_start: np.ndarray,
    clip_end: np.ndarray,
) -> np.ndarray:
    segment = end - start
    clip_edge = clip_end - clip_start
    denominator = segment[0] * clip_edge[1] - segment[1] * clip_edge[0]

    if abs(float(denominator)) < 1e-8:
        return end.astype(np.float32)

    delta = clip_start - start
    t = (delta[0] * clip_edge[1] - delta[1] * clip_edge[0]) / denominator
    return (start + t * segment).astype(np.float32)


def sutherland_hodgman_clip(
    subject_polygon: np.ndarray,
    clip_polygon: np.ndarray,
) -> np.ndarray:
    """Clip one convex polygon by another using Sutherland-Hodgman."""

    subject = normalize_polygon(subject_polygon)
    clipper = normalize_polygon(clip_polygon)
    output = subject
    clip_orientation = 1.0 if signed_polygon_area(clipper) >= 0 else -1.0

    def inside(point: np.ndarray, edge_start: np.ndarray, edge_end: np.ndarray) -> bool:
        edge = edge_end - edge_start
        rel = point - edge_start
        cross = edge[0] * rel[1] - edge[1] * rel[0]
        return bool(cross * clip_orientation >= -1e-6)

    for i, edge_start in enumerate(clipper):
        edge_end = clipper[(i + 1) % len(clipper)]
        input_list = output
        if len(input_list) == 0:
            break

        output_points: list[np.ndarray] = []
        previous = input_list[-1]
        previous_inside = inside(previous, edge_start, edge_end)

        for current in input_list:
            current_inside = inside(current, edge_start, edge_end)

            if current_inside:
                if not previous_inside:
                    output_points.append(
                        _line_intersection(previous, current, edge_start, edge_end)
                    )
                output_points.append(current.astype(np.float32))
            elif previous_inside:
                output_points.append(
                    _line_intersection(previous, current, edge_start, edge_end)
                )

            previous = current
            previous_inside = current_inside

        output = (
            np.asarray(output_points, dtype=np.float32)
            if output_points
            else np.empty((0, 2), dtype=np.float32)
        )

    return output


def polygon_iou(polygon_a: np.ndarray, polygon_b: np.ndarray) -> float:
    a = normalize_polygon(polygon_a)
    b = normalize_polygon(polygon_b)
    area_a = polygon_area(a)
    area_b = polygon_area(b)

    if area_a <= 0.0 or area_b <= 0.0:
        return 0.0

    intersection = sutherland_hodgman_clip(a, b)
    intersection_area = polygon_area(intersection) if len(intersection) >= 3 else 0.0
    union_area = area_a + area_b - intersection_area

    if union_area <= 0.0:
        return 0.0

    return float(intersection_area / union_area)


def transform_polygon(polygon: np.ndarray, homography_matrix: np.ndarray | None) -> np.ndarray:
    polygon = normalize_polygon(polygon)
    if homography_matrix is None:
        return polygon
    warped = cv2.perspectiveTransform(
        polygon.reshape(1, -1, 2).astype(np.float32),
        homography_matrix.astype(np.float64),
    )
    return warped.reshape(-1, 2).astype(np.float32)


@dataclass
class ParkingSlot:
    slot_id: str
    polygon: np.ndarray
    occupied: bool = False
    vote_buffer: deque[bool] = field(default_factory=lambda: deque(maxlen=5))
    confidence_buffer: deque[float] = field(default_factory=lambda: deque(maxlen=5))
    confidence: float = 1.0
    last_changed: float = field(default_factory=time.time)
    occupied_since: float | None = None
    smoothing_window: int = 5

    def __post_init__(self) -> None:
        self.polygon = normalize_polygon(self.polygon)
        if self.vote_buffer.maxlen != self.smoothing_window:
            self.vote_buffer = deque(self.vote_buffer, maxlen=self.smoothing_window)
        if self.confidence_buffer.maxlen != self.smoothing_window:
            self.confidence_buffer = deque(
                self.confidence_buffer,
                maxlen=self.smoothing_window,
            )
        if self.occupied and self.occupied_since is None:
            self.occupied_since = self.last_changed

    def update_votes(self, is_occupied: bool, confidence: float = 1.0) -> bool:
        """Update temporal votes and return True when the stable state flips."""

        self.vote_buffer.append(bool(is_occupied))
        self.confidence_buffer.append(float(np.clip(confidence, 0.0, 1.0)))
        self.confidence = float(np.mean(self.confidence_buffer))

        if len(self.vote_buffer) < self.smoothing_window:
            return False

        occupied_votes = sum(self.vote_buffer)
        next_state = self.occupied

        if not self.occupied and occupied_votes >= 4:
            next_state = True
        elif self.occupied and occupied_votes <= 2:
            next_state = False

        if next_state == self.occupied:
            return False

        now = time.time()
        self.occupied = next_state
        self.last_changed = now
        self.occupied_since = now if next_state else None
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "occupied": self.occupied,
            "confidence": round(float(self.confidence), 4),
            "last_changed": self.last_changed,
            "occupied_since": self.occupied_since,
            "polygon": self.polygon.astype(float).round(2).tolist(),
        }


class ParkingDetector:
    def __init__(
        self,
        camera_id: str,
        model_path: str | None = "yolov8m-obb.pt",
        iou_threshold: float | None = None,
        confidence_threshold: float | None = None,
        smoothing_window: int | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.model_path = model_path or os.getenv("MODEL_PATH", "yolov8m-obb.pt")
        self.iou_threshold = (
            iou_threshold if iou_threshold is not None else _env_float("IOU_THRESHOLD", 0.40)
        )
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else _env_float("CONFIDENCE_THRESHOLD", 0.45)
        )
        self.smoothing_window = (
            smoothing_window
            if smoothing_window is not None
            else _env_int("SMOOTHING_WINDOW", 5)
        )
        self.slots: dict[str, ParkingSlot] = {}
        self._slot_lock = threading.RLock()
        self.homography_matrix: np.ndarray | None = None
        self.model = None
        self.last_detections: list[dict[str, Any]] = []

        if self.model_path and self.model_path.lower() not in {"none", "disabled"}:
            self.model = _get_shared_yolo(self.model_path)
        self.vehicle_class_ids = self._resolve_vehicle_class_ids()

    def set_homography(
        self,
        src_points: Iterable[Iterable[float]],
        dst_points: Iterable[Iterable[float]],
    ) -> np.ndarray:
        src = np.asarray(src_points, dtype=np.float32)
        dst = np.asarray(dst_points, dtype=np.float32)
        if src.shape != (4, 2) or dst.shape != (4, 2):
            raise ValueError("src_points and dst_points must each contain four [x, y] points")

        matrix, _ = cv2.findHomography(src, dst)
        if matrix is None:
            raise ValueError("could not compute homography from provided points")

        self.homography_matrix = matrix.astype(np.float64)
        return self.homography_matrix

    def load_slots(self, slots: list[dict[str, Any]]) -> None:
        with self._slot_lock:
            loaded: dict[str, ParkingSlot] = {}
            for slot in slots:
                slot_id = str(slot["slot_id"])
                previous = self.slots.get(slot_id)
                loaded[slot_id] = ParkingSlot(
                    slot_id=slot_id,
                    polygon=np.asarray(slot["polygon"], dtype=np.float32),
                    occupied=bool(slot.get("occupied", previous.occupied if previous else False)),
                    vote_buffer=deque(
                        previous.vote_buffer if previous else [],
                        maxlen=self.smoothing_window,
                    ),
                    confidence_buffer=deque(
                        previous.confidence_buffer if previous else [],
                        maxlen=self.smoothing_window,
                    ),
                    confidence=float(
                        slot.get("confidence", previous.confidence if previous else 1.0)
                    ),
                    last_changed=float(
                        slot.get("last_changed", previous.last_changed if previous else time.time())
                    ),
                    occupied_since=slot.get(
                        "occupied_since",
                        previous.occupied_since if previous else None,
                    ),
                    smoothing_window=self.smoothing_window,
                )
            self.slots = loaded

    def get_slots(self) -> list[dict[str, Any]]:
        with self._slot_lock:
            return [slot.to_dict() for slot in sorted(self.slots.values(), key=lambda s: s.slot_id)]

    def process_frame(self, frame: np.ndarray) -> tuple[list[dict[str, Any]], np.ndarray]:
        if frame is None or frame.size == 0:
            raise ValueError("frame must be a non-empty image")

        annotated_frame = frame.copy()
        detections = self._detect_vehicle_polygons(frame)
        self.last_detections = [
            {
                "class_id": detection["class_id"],
                "class_name": detection["class_name"],
                "confidence": round(float(detection["confidence"]), 4),
                "polygon": detection["polygon"].astype(float).round(2).tolist(),
            }
            for detection in detections
        ]
        changed_slots: list[dict[str, Any]] = []
        overlay = annotated_frame.copy()

        with self._slot_lock:
            for slot in self.slots.values():
                slot_poly_for_iou = transform_polygon(slot.polygon, self.homography_matrix)
                occupied_vote = False
                vote_confidence = 1.0
                best_iou = 0.0

                for detection in detections:
                    vehicle_polygon = transform_polygon(
                        detection["polygon"],
                        self.homography_matrix,
                    )
                    iou = polygon_iou(slot_poly_for_iou, vehicle_polygon)
                    if iou > best_iou:
                        best_iou = iou
                        vote_confidence = detection["confidence"]
                    if iou >= self.iou_threshold:
                        occupied_vote = True

                if not occupied_vote:
                    vote_confidence = max(0.0, min(1.0, 1.0 - best_iou))

                changed = slot.update_votes(occupied_vote, vote_confidence)
                if changed:
                    changed_slots.append(slot.to_dict())

                color = (45, 55, 235) if slot.occupied else (54, 214, 112)
                points = slot.polygon.astype(np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(overlay, [points], color)
                cv2.polylines(annotated_frame, [points], True, color, 2, cv2.LINE_AA)
                center = tuple(np.mean(slot.polygon, axis=0).astype(int))
                cv2.putText(
                    annotated_frame,
                    slot.slot_id,
                    center,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

        cv2.addWeighted(overlay, 0.22, annotated_frame, 0.78, 0, annotated_frame)

        for detection in detections:
            points = detection["polygon"].astype(np.int32).reshape((-1, 1, 2))
            cv2.polylines(annotated_frame, [points], True, (255, 194, 87), 1, cv2.LINE_AA)

        return changed_slots, annotated_frame

    def _detect_vehicle_polygons(self, frame: np.ndarray) -> list[dict[str, Any]]:
        if self.model is None:
            return []

        class_filter = self.vehicle_class_ids or list(VEHICLE_CLASSES)
        results = self.model.predict(
            frame,
            conf=self.confidence_threshold,
            classes=class_filter,
            verbose=False,
        )
        if not results:
            return []

        result = results[0]
        obb = getattr(result, "obb", None)
        if obb is None:
            return []

        polygons = _to_numpy(getattr(obb, "xyxyxyxy", None))
        classes = _to_numpy(getattr(obb, "cls", None)).astype(int)
        confidences = _to_numpy(getattr(obb, "conf", None)).astype(float)

        if polygons.size == 0:
            return []
        if polygons.ndim == 2 and polygons.shape[1] == 8:
            polygons = polygons.reshape(-1, 4, 2)

        detections: list[dict[str, Any]] = []
        for polygon, class_id, confidence in zip(polygons, classes, confidences, strict=False):
            class_name = self._class_name(class_id)
            if class_id not in class_filter and class_name.lower() not in VEHICLE_CLASS_NAMES:
                continue
            if float(confidence) < self.confidence_threshold:
                continue
            detections.append(
                {
                    "class_id": int(class_id),
                    "class_name": class_name,
                    "confidence": float(confidence),
                    "polygon": normalize_polygon(polygon),
                }
            )

        return detections

    def _resolve_vehicle_class_ids(self) -> list[int]:
        if self.model is None:
            return list(VEHICLE_CLASSES)

        names = getattr(self.model, "names", {}) or {}
        resolved = [
            int(class_id)
            for class_id, name in names.items()
            if str(name).strip().lower() in VEHICLE_CLASS_NAMES
        ]
        return sorted(set(resolved or VEHICLE_CLASSES))

    def _class_name(self, class_id: int) -> str:
        names = getattr(self.model, "names", {}) if self.model is not None else {}
        return str(names.get(int(class_id), VEHICLE_CLASSES.get(int(class_id), class_id)))
