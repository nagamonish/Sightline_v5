import math

import numpy as np

from backend.core.detector import ParkingSlot, polygon_iou


def rotated_square(center, side, angle_degrees):
    half = side / 2
    points = np.array(
        [
            [-half, -half],
            [half, -half],
            [half, half],
            [-half, half],
        ],
        dtype=np.float32,
    )
    angle = math.radians(angle_degrees)
    rotation = np.array(
        [
            [math.cos(angle), -math.sin(angle)],
            [math.sin(angle), math.cos(angle)],
        ],
        dtype=np.float32,
    )
    return points @ rotation.T + np.asarray(center, dtype=np.float32)


def test_polygon_iou_overlapping_rotated_squares():
    angle = 30
    first = rotated_square((0, 0), 2, angle)
    shift = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
    second = rotated_square(shift, 2, angle)

    assert polygon_iou(first, second) == pytest_approx(1 / 3)
    assert polygon_iou(second, first) == pytest_approx(1 / 3)
    assert polygon_iou(first, second[::-1]) == pytest_approx(1 / 3)


def test_parking_slot_hysteresis_requires_stable_votes():
    slot = ParkingSlot(
        slot_id="A1",
        polygon=np.array([[0, 0], [2, 0], [2, 4], [0, 4]], dtype=np.float32),
    )

    assert not slot.update_votes(True, 0.9)
    assert not slot.update_votes(True, 0.9)
    assert not slot.update_votes(False, 0.9)
    assert not slot.update_votes(True, 0.9)
    assert slot.update_votes(True, 0.9)
    assert slot.occupied

    assert not slot.update_votes(True, 0.9)
    assert not slot.update_votes(False, 0.9)
    assert not slot.update_votes(False, 0.9)
    assert slot.update_votes(False, 0.9)
    assert not slot.occupied


def pytest_approx(value):
    import pytest

    return pytest.approx(value, rel=1e-5, abs=1e-5)


def test_shared_yolo_model_loaded_once_across_detectors(monkeypatch):
    """Multiple ParkingDetectors that point at the same checkpoint must share
    one YOLO instance — that's the whole point of the cache."""
    import sys
    import types

    from backend.core import detector as det

    det._model_cache.clear()
    yolo_paths_loaded: list[str] = []

    class _StubYOLO:
        names = {2: "car", 3: "motorcycle"}

        def __init__(self, path: str) -> None:
            yolo_paths_loaded.append(path)

    fake_ultralytics = types.ModuleType("ultralytics")
    fake_ultralytics.YOLO = _StubYOLO
    monkeypatch.setitem(sys.modules, "ultralytics", fake_ultralytics)

    d1 = det.ParkingDetector("cam1", model_path="fake.pt")
    d2 = det.ParkingDetector("cam2", model_path="fake.pt")
    d3 = det.ParkingDetector("cam3", model_path="fake.pt")

    assert yolo_paths_loaded == ["fake.pt"], (
        "YOLO should be constructed exactly once for repeated model paths"
    )
    assert d1.model is d2.model is d3.model

    # A different checkpoint loads a second instance.
    d4 = det.ParkingDetector("cam4", model_path="other.pt")
    assert yolo_paths_loaded == ["fake.pt", "other.pt"]
    assert d4.model is not d1.model

    det._model_cache.clear()
