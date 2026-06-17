# Model Card

## Model

Sightline is designed for YOLOv8 oriented bounding box models from Ultralytics.

Recommended local testing model:

```text
yolov8n-obb.pt
```

Commercial or higher-accuracy target model:

```text
yolov8m-obb.pt
```

Model weights are not committed to this repository.

## Intended Use

The model detects vehicles in parking lot camera frames and returns oriented bounding boxes. Sightline compares those boxes against parking-space polygons to estimate occupancy.

## Detected Classes

The detector is intended to use vehicle classes only:

- car
- motorcycle
- bus
- truck

## Inputs

- RTSP camera frames.
- Local demo streams from MediaMTX and FFmpeg.
- Image coordinates matching the configured parking slot polygons.

## Outputs

- Vehicle oriented bounding boxes.
- Per-slot occupied or free state.
- Per-slot confidence and timestamps.
- Annotated MJPEG frames for the dashboard.

## Known Limitations

- Accuracy depends heavily on camera angle, image quality, lighting, and weather.
- Heavy shadows, glare, snow, rain, night scenes, and occlusions can reduce reliability.
- Poorly drawn parking polygons can produce incorrect occupancy.
- A model trained on generic vehicle data may not perform well on every lot layout.
- Very small or distant vehicles can be missed.
- Non-vehicle objects can still be confused with vehicles in difficult scenes.
- The current analytics implementation counts events and should be improved before production reporting.

## Calibration Requirements

For best results:

- Use a fixed camera.
- Avoid moving or zooming the camera after calibration.
- Draw one polygon per actual parking space.
- Use footage where parking stall boundaries are visible.
- Recalibrate after changing camera position, resolution, crop, or perspective transform.

## Confidence And Smoothing

Default settings:

```text
CONFIDENCE_THRESHOLD=0.45
IOU_THRESHOLD=0.40
SMOOTHING_WINDOW=5
```

For local demos, lower thresholds may be useful:

```text
CONFIDENCE_THRESHOLD=0.15
IOU_THRESHOLD=0.20
```

Production deployments should tune thresholds with real validation footage from the target camera.

## Human Review

Sightline should not be treated as a fully autonomous enforcement system without human review, validation, and operational safeguards.
