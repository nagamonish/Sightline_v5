"""Auto-discover parking slots from a live YOLO feed.

What this is for
----------------
The bundled PKLot sample ships 100 hand-labeled slot polygons. That's fine
for the demo, but it caps the lot at exactly 100 spaces and gives you nothing
for empty-bay tracking on a real camera you haven't calibrated yet.

This script asks the running backend for the latest YOLO detections on a
camera and turns them into a full slot map in two passes:

  1. Every detected vehicle becomes an "occupied" slot polygon, no matter
     how many vehicles the model sees. The fixed 100-slot ceiling goes away
     and the count becomes "however many cars the model actually finds".

  2. Vehicles are then grouped into rows by their vertical position, and the
     horizontal gaps between adjacent cars in each row are measured. Any gap
     wide enough to plausibly hold another car gets an "empty" slot polygon
     dropped into it. Those bays are tracked as available from frame one, so
     the dashboard shows red AND green from the start instead of only red.

The merged list is pushed to POST /cameras/<id>/slots and the detector's
normal smoothing logic takes over from there.

What this is NOT
----------------
* This is not a calibration replacement. Empty bays that aren't between two
  detected cars (e.g. an entire empty row, or the open end of a row) can't
  be inferred from car detections alone -- you'd need a parking-line model
  or a painted-marker model for that.

* The row clustering is geometric, not semantic. On a top-down lot image
  it works fine; on a tilted/perspective view you should set a homography
  via the calibration wizard first so that "same row" means "same y" in
  the rectified frame.

Tuning knobs
------------
GAP_MIN_FRACTION  How wide a gap has to be (as a multiple of the row's
                  median car width) before we treat it as an empty bay.
                  0.7 means "70% of a car wide" -- intentionally generous
                  so we don't lose narrow compact-car spots.

ROW_Y_TOLERANCE   How close two cars' vertical centers have to be to count
                  as the same row, as a multiple of the median car height.
                  Lower this if rows are bleeding into each other; raise it
                  if a single row is being split.

Usage
-----
    python scripts/infer_empty_slots.py --base-url http://127.0.0.1:8000 --camera cam1
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from statistics import median


GAP_MIN_FRACTION = 0.7
ROW_Y_TOLERANCE = 0.6


def get_detections(base_url: str, camera_id: str) -> list[dict]:
    """Pull the most recent YOLO detections from the backend."""
    resp = urllib.request.urlopen(f"{base_url}/cameras/{camera_id}/detections").read()
    return json.loads(resp).get("detections", [])


def post_slots(base_url: str, camera_id: str, slots: list[dict]) -> int:
    """Replace the camera's slot list. Returns the count the backend stored."""
    req = urllib.request.Request(
        f"{base_url}/cameras/{camera_id}/slots",
        method="POST",
        data=json.dumps({"slots": slots}).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    return len(resp)


def polygon_bounds(poly: list[list[float]]) -> tuple[float, float, float, float]:
    """Axis-aligned bounding box of a polygon as (x1, y1, x2, y2)."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _enrich(cars: list[dict]) -> list[dict]:
    """Decorate each detection with the bounds + centroid we'll reason about."""
    enriched = []
    for car in cars:
        x1, y1, x2, y2 = polygon_bounds(car["polygon"])
        enriched.append({
            "polygon": car["polygon"],
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "cx": (x1 + x2) / 2,
            "cy": (y1 + y2) / 2,
            "w": x2 - x1,
            "h": y2 - y1,
        })
    return enriched


def cluster_into_rows(cars: list[dict]) -> list[list[dict]]:
    """Group cars whose vertical centers are within ROW_Y_TOLERANCE of each other.

    Walks the cars sorted by y-centroid and starts a new row whenever the next
    car is more than ROW_Y_TOLERANCE * median_car_height away vertically.
    """
    enriched = _enrich(cars)
    enriched.sort(key=lambda c: c["cy"])
    if not enriched:
        return []
    median_h = median(c["h"] for c in enriched)
    rows: list[list[dict]] = []
    current: list[dict] = []
    for car in enriched:
        if not current or abs(car["cy"] - current[-1]["cy"]) <= ROW_Y_TOLERANCE * median_h:
            current.append(car)
        else:
            rows.append(current)
            current = [car]
    if current:
        rows.append(current)
    return rows


def empties_in_row(row: list[dict]) -> list[list[list[float]]]:
    """Look for x-gaps between adjacent cars in one row and emit polygons that
    fill each gap. The polygons' y-extent is the average of the row's cars."""
    if len(row) < 2:
        return []
    row.sort(key=lambda c: c["cx"])
    median_w = median(c["w"] for c in row)
    avg_y1 = sum(c["y1"] for c in row) / len(row)
    avg_y2 = sum(c["y2"] for c in row) / len(row)

    empties: list[list[list[float]]] = []
    for prev, nxt in zip(row[:-1], row[1:]):
        gap_x1 = prev["x2"]
        gap_x2 = nxt["x1"]
        gap_w = gap_x2 - gap_x1
        if gap_w < GAP_MIN_FRACTION * median_w:
            continue
        # A wider gap might hold more than one missed bay; carve it into slots
        # of one median-car-width each.
        n_empties = max(1, round(gap_w / median_w))
        slot_w = gap_w / n_empties
        for i in range(n_empties):
            sx1 = gap_x1 + i * slot_w
            sx2 = sx1 + slot_w
            empties.append([
                [sx1, avg_y1],
                [sx2, avg_y1],
                [sx2, avg_y2],
                [sx1, avg_y2],
            ])
    return empties


def build_slots(cars: list[dict]) -> tuple[list[dict], int, int]:
    """Return (slots, occupied_count, empty_count)."""
    slots: list[dict] = []
    for index, car in enumerate(cars):
        slots.append({"slot_id": f"C{index + 1:03d}", "polygon": car["polygon"]})

    rows = cluster_into_rows(cars)
    empty_count = 0
    for row in rows:
        for poly in empties_in_row(row):
            empty_count += 1
            slots.append({"slot_id": f"E{empty_count:03d}", "polygon": poly})
    return slots, len(cars), empty_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend root, e.g. http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--camera",
        default="cam1",
        help="Camera ID registered with the backend",
    )
    args = parser.parse_args()

    cars = get_detections(args.base_url, args.camera)
    if not cars:
        print(
            "No detections yet. Make sure the camera is connected and the "
            "RTSP stream is producing frames before running this.",
            file=sys.stderr,
        )
        return 1

    slots, occupied, empty = build_slots(cars)
    rows = cluster_into_rows(cars)
    print(f"Detected vehicles: {occupied}")
    print(f"Rows clustered:    {len(rows)} (sizes {[len(r) for r in rows]})")
    print(f"Empty bays inferred: {empty}")
    print(f"Total slots pushed: {len(slots)}")

    stored = post_slots(args.base_url, args.camera, slots)
    print(f"Backend stored: {stored} slots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
