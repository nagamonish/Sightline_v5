from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass
class SlotCandidate:
    polygon: np.ndarray
    score: float
    source: str

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        x, y, w, h = cv2.boundingRect(self.polygon.astype(np.float32))
        return float(x), float(y), float(x + w), float(y + h)

    @property
    def area(self) -> float:
        return float(cv2.contourArea(self.polygon.astype(np.float32)))


def _bbox_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    intersection = iw * ih
    if intersection <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def _order_polygon(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    center = np.mean(points, axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    return ordered.astype(np.float32)


def _candidate_from_rect(
    rect: tuple[tuple[float, float], tuple[float, float], float],
    frame_area: float,
    source: str,
    score_boost: float = 0.0,
) -> SlotCandidate | None:
    (width, height) = rect[1]
    if width <= 1 or height <= 1:
        return None

    short = min(width, height)
    long = max(width, height)
    aspect_ratio = short / long
    polygon = _order_polygon(cv2.boxPoints(rect))
    area = float(cv2.contourArea(polygon))
    area_ratio = area / frame_area if frame_area else 0.0

    if not (0.25 <= aspect_ratio <= 0.75):
        return None
    if not (0.005 <= area_ratio <= 0.12):
        return None

    score = (1.0 - abs(aspect_ratio - 0.5)) + score_boost
    return SlotCandidate(polygon=polygon, score=score, source=source)


def _detect_hough_candidates(edges: np.ndarray, frame_area: float) -> list[SlotCandidate]:
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=55,
        minLineLength=max(24, int(min(edges.shape[:2]) * 0.06)),
        maxLineGap=18,
    )
    if lines is None:
        return []

    segments: list[dict[str, Any]] = []
    for line in lines[:, 0, :]:
        x1, y1, x2, y2 = map(float, line)
        dx = x2 - x1
        dy = y2 - y1
        length = float(np.hypot(dx, dy))
        if length < 24:
            continue
        angle = (np.degrees(np.arctan2(dy, dx)) + 180) % 180
        midpoint = np.array([(x1 + x2) / 2, (y1 + y2) / 2], dtype=np.float32)
        segments.append(
            {
                "points": np.array([[x1, y1], [x2, y2]], dtype=np.float32),
                "angle": angle,
                "length": length,
                "midpoint": midpoint,
            }
        )

    candidates: list[SlotCandidate] = []
    for index, first in enumerate(segments):
        for second in segments[index + 1 :]:
            angle_delta = abs(first["angle"] - second["angle"])
            angle_delta = min(angle_delta, 180 - angle_delta)
            if angle_delta > 8:
                continue

            separation = float(np.linalg.norm(first["midpoint"] - second["midpoint"]))
            avg_length = (first["length"] + second["length"]) / 2
            if separation < avg_length * 0.25 or separation > avg_length * 1.8:
                continue

            points = np.vstack([first["points"], second["points"]]).astype(np.float32)
            rect = cv2.minAreaRect(points)
            candidate = _candidate_from_rect(rect, frame_area, "hough", 0.18)
            if candidate is not None:
                candidates.append(candidate)

    return candidates


def _detect_contour_candidates(edges: np.ndarray, frame_area: float) -> list[SlotCandidate]:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[SlotCandidate] = []
    for contour in contours:
        if len(contour) < 4:
            continue
        rect = cv2.minAreaRect(contour)
        candidate = _candidate_from_rect(rect, frame_area, "contour")
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _nms(candidates: list[SlotCandidate], threshold: float = 0.35) -> list[SlotCandidate]:
    kept: list[SlotCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        if all(_bbox_iou(candidate.bbox, existing.bbox) < threshold for existing in kept):
            kept.append(candidate)
    return kept


def auto_detect_parking_slots(frame: np.ndarray) -> list[dict[str, Any]]:
    if frame is None or frame.size == 0:
        raise ValueError("frame must be a non-empty image")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame.copy()
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    frame_area = float(frame.shape[0] * frame.shape[1])

    candidates = _detect_hough_candidates(edges, frame_area)
    candidates.extend(_detect_contour_candidates(edges, frame_area))
    deduped = _nms(candidates)

    deduped.sort(key=lambda item: (float(np.mean(item.polygon[:, 1])), float(np.mean(item.polygon[:, 0]))))
    return [
        {
            "slot_id": f"A{index + 1}",
            "polygon": candidate.polygon.astype(float).round(2).tolist(),
            "score": round(float(candidate.score), 4),
            "source": candidate.source,
        }
        for index, candidate in enumerate(deduped)
    ]
