# Local Setup

This guide starts Sightline locally without a physical camera by publishing a sample image to a local RTSP server.

## Prerequisites

- Python 3.11
- Node.js 20 or newer
- FFmpeg
- MediaMTX
- Git

On macOS with Homebrew:

```bash
brew install python@3.11 node ffmpeg mediamtx git
```

## Clone And Install

```bash
git clone https://github.com/nagamonish/Sightline_v5.git
cd Sightline_v5

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend
npm install
cd ..
```

## Download A Local Model

For local CPU testing, the smaller OBB model is easier to run:

```bash
source .venv/bin/activate
python - <<'PY'
from ultralytics import YOLO
YOLO("yolov8n-obb.pt")
PY
```

## Optional Environment File

```bash
cp .env.example .env
```

The backend can run in memory mode for local testing:

```text
DATABASE_URL=memory
```

## Start The Local Demo

Use four terminal windows from the repository root.

### Terminal 1: RTSP Server

```bash
mediamtx
```

### Terminal 2: Publish Sample Image To RTSP

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

### Terminal 3: Backend

```bash
source .venv/bin/activate

DATABASE_URL=memory \
MODEL_PATH=yolov8n-obb.pt \
CONFIDENCE_THRESHOLD=0.15 \
IOU_THRESHOLD=0.20 \
.venv/bin/uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

### Terminal 4: Frontend

```bash
cd frontend
npm run dev
```

Open:

```text
http://localhost:5173
```

## Add The Sample Camera

In the dashboard:

1. Click `Add`.
2. Camera ID: `cam1`.
3. Name: `Sample Lot 1`.
4. RTSP URL: `rtsp://127.0.0.1:8554/sightline`.
5. Click `Load PKLot`.

Expected result: 100 mapped parking spaces with live occupancy counts.

## Useful Local Checks

Check the RTSP stream:

```bash
ffprobe -rtsp_transport tcp -v error \
  -show_entries stream=codec_type,width,height \
  -of json \
  rtsp://127.0.0.1:8554/sightline
```

Check the backend:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/cameras
```

Run backend tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

Build the frontend:

```bash
cd frontend
npm run build
```
