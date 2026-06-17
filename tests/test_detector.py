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


def _square_polygon():
    return np.array([[0, 0], [2, 0], [2, 4], [0, 4]], dtype=np.float32)


def test_smoothing_window_3_scales_thresholds():
    slot = ParkingSlot(slot_id="A1", polygon=_square_polygon(), smoothing_window=3)

    # ceil(3 * 0.8) = 3 -> need all three votes positive to flip to occupied.
    assert slot._occupied_threshold == 3
    # floor(3 * 0.4) = 1 -> need <= 1 positive vote in window to flip to free.
    assert slot._free_threshold == 1

    assert not slot.update_votes(True)
    assert not slot.update_votes(True)
    assert slot.update_votes(True)  # third positive vote flips
    assert slot.occupied

    assert not slot.update_votes(True)   # window=[T,T,T] still 3 positives, stays occupied
    assert not slot.update_votes(False)  # window=[T,T,F] = 2 positives, above free threshold
    assert slot.update_votes(False)      # window=[T,F,F] = 1 positive, flips to free
    assert not slot.occupied


def test_smoothing_window_7_scales_thresholds():
    slot = ParkingSlot(slot_id="A1", polygon=_square_polygon(), smoothing_window=7)

    # ceil(7 * 0.8) = 6 to occupy, floor(7 * 0.4) = 2 to free.
    assert slot._occupied_threshold == 6
    assert slot._free_threshold == 2

    # Two falses + five trues fills the window with only 5 positives -> no flip.
    assert not slot.update_votes(False)
    assert not slot.update_votes(False)
    for _ in range(5):
        assert not slot.update_votes(True)
    # Window is now [F,F,T,T,T,T,T] (5 positives, threshold 6). One more true
    # evicts the oldest false and brings the count to 6 -> flip.
    assert slot.update_votes(True)
    assert slot.occupied

    # Slot is occupied; need <= 2 positives to flip back. Stay > 2 first.
    assert not slot.update_votes(False)  # [F,T,T,T,T,T,F] -> 5 positives
    assert not slot.update_votes(False)  # [T,T,T,T,T,F,F] -> 5 positives
    for _ in range(2):
        # Still above the free threshold of 2.
        assert not slot.update_votes(False)
    # [T,T,F,F,F,F,F] -> 2 positives, <= 2 free threshold -> flip back.
    assert slot.update_votes(False)
    assert not slot.occupied


def test_smoothing_window_1_flips_every_frame():
    """Degenerate window=1 should still behave sensibly thanks to the max(1, ...) floor."""
    slot = ParkingSlot(slot_id="A1", polygon=_square_polygon(), smoothing_window=1)

    assert slot._occupied_threshold == 1
    assert slot._free_threshold == 0

    assert slot.update_votes(True)  # 1/1 positive → occupy
    assert slot.occupied
    assert slot.update_votes(False)  # 0/1 positive → free
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
