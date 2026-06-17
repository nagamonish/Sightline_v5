# API Examples

These examples assume the backend is running at:

```text
http://localhost:8000
```

And the local RTSP demo stream is:

```text
rtsp://127.0.0.1:8554/parkiq
```

## Health

```bash
curl http://localhost:8000/health
```

## Add A Camera

```bash
curl -X POST http://localhost:8000/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "camera_id": "cam1",
    "name": "Sample Lot 1",
    "rtsp_url": "rtsp://127.0.0.1:8554/parkiq",
    "slots": []
  }'
```

## List Cameras

```bash
curl http://localhost:8000/cameras
```

## Load PKLot Sample Slots

```bash
curl -X POST http://localhost:8000/cameras/cam1/samples/pklot
```

## Get Current Slots

```bash
curl http://localhost:8000/cameras/cam1/slots
```

## Update Slots

```bash
curl -X POST http://localhost:8000/cameras/cam1/slots \
  -H "Content-Type: application/json" \
  -d '{
    "slots": [
      {
        "slot_id": "A1",
        "polygon": [[100, 100], [180, 100], [180, 220], [100, 220]]
      }
    ]
  }'
```

## Trigger Auto-Calibration

```bash
curl -X POST http://localhost:8000/cameras/cam1/calibrate
```

## Set Homography

```bash
curl -X POST http://localhost:8000/cameras/cam1/homography \
  -H "Content-Type: application/json" \
  -d '{
    "src_points": [[0, 0], [1280, 0], [1280, 720], [0, 720]],
    "dst_points": [[0, 0], [1280, 0], [1280, 720], [0, 720]]
  }'
```

## Get Summary

```bash
curl http://localhost:8000/summary
```

## Analytics History

```bash
curl "http://localhost:8000/analytics/cam1/history?hours=24"
```

## Peak Hours

```bash
curl http://localhost:8000/analytics/cam1/peak-hours
```

## MJPEG Stream

Open in a browser:

```text
http://localhost:8000/cameras/cam1/stream
```

## WebSocket

The dashboard connects to:

```text
ws://localhost:8000/ws
```

Example messages:

```json
{"type": "full_state", "cameras": {}, "summary": []}
```

```json
{"type": "occupancy_update", "camera_id": "cam1", "slots": [], "summary": []}
```
