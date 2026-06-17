# Troubleshooting

## Docker Is Not Installed

You can run the local demo without Docker. Use the steps in [LOCAL_SETUP.md](LOCAL_SETUP.md).

On macOS, Docker Desktop can be installed from Docker's website. After installing it, restart the terminal and run:

```bash
docker --version
```

## Port 8000 Is Already In Use

Find the process:

```bash
lsof -i :8000
```

Stop the existing backend process, or start the backend on a different port:

```bash
.venv/bin/uvicorn backend.api.main:app --host 0.0.0.0 --port 8001
```

If you use port 8001, update the frontend env:

```bash
VITE_API_URL=http://localhost:8001 VITE_WS_URL=ws://localhost:8001/ws npm run dev
```

## Frontend Says The Backend Is Offline

Check the backend health endpoint:

```bash
curl http://localhost:8000/health
```

If it fails, restart the backend. If it works, check that the frontend has the right `VITE_API_URL` and `VITE_WS_URL`.

## RTSP Link Does Not Work

Start MediaMTX first:

```bash
mediamtx
```

Then publish the stream with FFmpeg:

```bash
ffmpeg -re -loop 1 -framerate 5 \
  -i sample-data/pklot/preview.jpg \
  -vf "format=yuv420p" \
  -an \
  -c:v libx264 \
  -preset ultrafast \
  -tune zerolatency \
  -r 5 \
  -g 10 \
  -f rtsp \
  -rtsp_transport tcp \
  rtsp://127.0.0.1:8554/sightline
```

Verify it:

```bash
ffprobe -rtsp_transport tcp -v error \
  -show_entries stream=codec_type,width,height \
  -of json \
  rtsp://127.0.0.1:8554/sightline
```

## MediaMTX Says Path Is Not Configured

Use the included config file from the repo root:

```bash
mediamtx mediamtx.yml
```

The expected local path is:

```text
rtsp://127.0.0.1:8554/sightline
```

## The App Shows Sample Missing

Recreate the PKLot fixture:

```bash
source .venv/bin/activate
python scripts/setup_pklot_sample.py --force
```

Then restart the backend and click `Load PKLot` again.

## The Backend Logs A Database Error

For local testing, this can be expected if Postgres is not running. Start the backend with memory mode:

```bash
DATABASE_URL=memory \
MODEL_PATH=yolov8n-obb.pt \
.venv/bin/uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

Memory mode does not persist cameras or events after the backend stops.

## The Model Is Missing

Download the small local model:

```bash
source .venv/bin/activate
python - <<'PY'
from ultralytics import YOLO
YOLO("yolov8n-obb.pt")
PY
```

Then start the backend with:

```bash
MODEL_PATH=yolov8n-obb.pt
```

## Detection Is Slow

Use the smaller model for local testing:

```text
MODEL_PATH=yolov8n-obb.pt
```

Keep the RTSP sample stream low frame rate:

```text
-framerate 5 -r 5
```

## Slots Look Misaligned

Use the tracked PKLot sample first. It has matching image and slot polygons:

```text
sample-data/pklot/preview.jpg
sample-data/pklot/slots.json
```

If you use a different image or video, you need matching slot polygons. The PKLot polygons are not transferable to unrelated footage.

## Tests Fail With No Module Named Backend

Run tests from the repo root with:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

A future test configuration should remove this extra environment variable.
