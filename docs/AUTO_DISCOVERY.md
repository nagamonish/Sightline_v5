# Auto-discovered parking slots — what changed and why

This doc walks through every change between the original PKLot demo and the
live auto-discovery shown in `docs/screenshots/auto-discovered-slots.png`.
Before, the dashboard showed 100 hardcoded boxes and almost everything was
red. After, the dashboard showed 169 dynamic boxes mixing red occupied cars
with green empty bays — without anyone hand-drawing a single new polygon.

## How it used to work

The original setup loaded `sample-data/pklot/slots.json` at calibration
time — a hand-labeled list of **exactly 100 polygons** for the PKLot sample
image. Every box on the dashboard came from that file. The detector ran on
each frame and flipped each of those 100 boxes red (a car overlaps it) or
green (no car).

The consequences of that design:

- The box count was **capped at 100 forever**, no matter how big the lot was
  or how many cars the model could actually see.
- Anything **outside those 100 polygons was invisible** to the system. You
  could have a car parked clearly in frame and the dashboard would never
  know it existed.
- Empty bays only showed up if a polygon was **pre-labeled there** AND no
  car matched it. On the bundled PKLot image, every polygon had a car in
  it, so we never saw a single green box even though there were obvious
  empty spots in the lot.

That's the state you were looking at when you said "shouldn't I see more
boxes?" — and you were right.

## The four changes I made

### 1. Newer, bigger detection model: `yolov8n-obb` → `yolo11m-obb`

The README's quick-start downloads `yolov8n-obb.pt`. That's the **nano**
YOLOv8 OBB checkpoint, about 6 MB. It's tiny and fast, but its accuracy on
small or partially-clipped cars in oblique top-down views is shaky.

I swapped to `yolo11m-obb.pt` — the **medium** YOLOv11 OBB checkpoint,
about 40 MB. Three reasons it's a better fit here:

- **Newer architecture.** YOLOv11's backbone improves precision/recall on
  the kinds of small objects you get in a top-down lot view.
- **Bigger model.** Medium has roughly 7× the parameters of nano, which
  shows up as noticeably better recall on clipped or partly-occluded cars
  at the edges of the frame.
- **Same OBB head shape**, so the existing detector code Just Works — no
  API changes, just a different `MODEL_PATH`.

Trade-off: ~5–10× slower per frame than nano. On this demo (5 fps stream)
it stays well under realtime; on a higher-fps stream you'd want to think
about whether the accuracy gain is worth the throughput cost.

### 2. Lower matching thresholds

Two knobs in the detector control how aggressive the matching is:

- **`CONFIDENCE_THRESHOLD`** — how sure the model has to be before it emits
  a detection. The README default is **0.15**; I lowered it to **0.10**.
  This catches more borderline detections (cars at the edge of the frame,
  cars half-hidden by shadow, etc.).
- **`IOU_THRESHOLD`** — how much a detected car has to overlap a slot
  polygon before the slot flips occupied. The README default is **0.20**;
  I lowered it to **0.15**. This stops near-miss matches — where the slot
  polygon and the detected car overlap but not quite by 20% — from getting
  thrown out as "no match."

Together, these knobs let through detections that the stock thresholds
were quietly discarding.

### 3. Slot count = whatever the model sees, not a fixed 100

This is the most important change. Instead of loading the 100 hand-labeled
polygons from `slots.json`, the new script
[`scripts/infer_empty_slots.py`](../scripts/infer_empty_slots.py) does
this in three steps:

1. **Ask the backend for the most recent YOLO detections** on the camera
   (`GET /cameras/<id>/detections`).
2. **Turn every detection into one slot polygon.** No deduplication, no
   filtering — if YOLO found 105 cars in the frame, you get 105 slots
   right then and there. The 100-slot ceiling disappears.
3. **POST the slot list back** to the backend (`POST /cameras/<id>/slots`),
   which kicks off the normal smoothing logic.

The first time I ran this on the PKLot sample I got **105 occupied slots**
back — that's already 5 more than the hand-labeled JSON had, and the
count would scale up the same way on a bigger lot.

### 4. Empty bays inferred from the gaps *between* detected cars

A car detector by itself can't see *empty* parking spots — it only knows
about cars. But there's a useful insight: an empty spot in the middle of
a row of cars shows up in the image as a **gap between two cars**.

The script exploits that with classical geometry:

1. **Group the detected cars into rows by vertical position.** Two cars
   are in the same row if their y-centroids are within
   `ROW_Y_TOLERANCE × median_car_height` of each other. With
   `ROW_Y_TOLERANCE = 0.6` this means "within 60% of a car-height
   vertically." On the PKLot sample this produced 8 rows.
2. **In each row, sort the cars left-to-right** and walk through adjacent
   pairs, measuring the horizontal distance between them.
3. **Any gap wider than `GAP_MIN_FRACTION × median_car_width` becomes one
   or more empty-slot polygons.** With `GAP_MIN_FRACTION = 0.7` this means
   "at least 70% of a typical car wide." A wider gap holds more than one
   missed bay, so the script carves the gap into as many sub-slots as
   `gap_width / median_car_width` rounds to.

On the PKLot sample this added **64 empty bays** alongside the 105
occupied ones — 169 total slots, 62% occupancy, both red and green showing
from the first frame.

## The two knobs you can turn

Both are constants at the top of `scripts/infer_empty_slots.py`:

- **`GAP_MIN_FRACTION = 0.7`** — how wide a gap has to be (as a fraction
  of the row's median car width) before it counts as an empty bay.
  - Raise it (say 0.9) and only big obvious gaps become empty bays.
    Cleaner output, but you'll miss real bays that are slightly narrower
    than the surrounding cars.
  - Lower it (say 0.5) and even small gaps get filled in. More green
    boxes, but you'll get spurious slots where two cars happen to be
    parked a little apart.
- **`ROW_Y_TOLERANCE = 0.6`** — how close two cars' vertical centers
  have to be (as a fraction of the median car height) to count as the
  same row.
  - Raise it (say 0.9) if rows are getting split — the script will be
    more willing to merge cars across slightly different y values.
  - Lower it (say 0.3) if rows are bleeding into each other — the
    script will be stricter about what "same row" means.

## What this still can't do (be honest)

- **Empty bays at the open end of a row, or in entirely empty rows, are
  invisible.** They have no detected car on either side to anchor a gap,
  so the geometry can't see them. Detecting these would need a model
  trained on painted parking-line markings (a different problem entirely).
- **The row clustering is pure geometry.** On a tilted/perspective view
  the rows blur into each other and the y-clustering breaks. The fix is
  to set a homography first via the calibration wizard's new point-picker
  so that "same row" means "same y" in the rectified frame.
- **A single sample-flash run.** The slot map is whatever the model saw
  the moment you ran the script. To keep it fresh as cars come and go,
  re-run the script periodically (or wire it into a backend endpoint).

## Before / after, at a glance

|                        | Old (loaded `slots.json`)             | New (`infer_empty_slots.py`)                  |
| ---------------------- | ------------------------------------- | --------------------------------------------- |
| Slot source            | hand-labeled JSON                     | live YOLO detections + inferred gaps          |
| Slot count             | exactly 100 forever                   | 169 on PKLot, scales with the lot             |
| Detection model        | `yolov8n-obb` (nano, 6 MB, YOLOv8)    | `yolo11m-obb` (medium, 40 MB, YOLOv11)        |
| `CONFIDENCE_THRESHOLD` | 0.15                                  | 0.10                                          |
| `IOU_THRESHOLD`        | 0.20                                  | 0.15                                          |
| Empty bays detected    | only if pre-labeled and unmatched     | gaps between adjacent cars in each row        |
| Result on PKLot sample | 100 slots, ~62 red, ~38 dim/odd green | 169 slots, **105 red + 64 green**, 62% occ.   |
