# Sightline

Sightline is a local AI parking detection demo. It reads an RTSP camera stream, detects vehicles with YOLOv8 OBB, maps detections onto parking space polygons, and shows live occupancy in a React dashboard.

The project includes a small PKLot sample so you can test the app without a real camera.

## License and use restrictions

This project is proprietary and all rights are reserved.

This repository is public only for review, demonstration, and portfolio visibility. It is not open source. You may view the repository, but you may not copy, use, modify, distribute, host, deploy, sell, or create derivative works from this code without prior written permission from Monish Munagala.

Unauthorized use may result in legal action. See [LICENSE](LICENSE) for the full terms.

Also see [NOTICE.md](NOTICE.md) and [SECURITY.md](SECURITY.md).

## Documentation

- [Local setup](docs/LOCAL_SETUP.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Demo media](docs/DEMO.md)
- [CI setup](docs/CI_SETUP.md)
- [Roadmap](ROADMAP.md)
- [Changelog](CHANGELOG.md)
- [API examples](API_EXAMPLES.md)
- [Model card](MODEL_CARD.md)
- [Dataset notice](DATASET_NOTICE.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Release checklist](RELEASE_CHECKLIST.md)

## Demo media

Clean sample image:

![PKLot sample parking lot](sample-data/pklot/preview.jpg)

Annotated reference image:

![PKLot slot overlay](sample-data/pklot/overlay.jpg)

RTSP URL to enter in the app:

```text
rtsp://127.0.0.1:8554/sightline
```

For the full demo flow, see [docs/DEMO.md](docs/DEMO.md).

## What you need

- Python 3.11
- Node.js 20 or newer
- FFmpeg
- MediaMTX
- Git

On macOS with Homebrew:

```bash
brew install python@3.11 node ffmpeg mediamtx git
```

## First time setup

From the project folder:

```bash
cd Sightline_v5
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Install frontend packages:

```bash
cd Sightline_v5/frontend
npm install
```

Download the smaller YOLO OBB model:

```bash
cd Sightline_v5
python - <<'PY'
from ultralytics import YOLO
YOLO("yolov8n-obb.pt")
PY
```

If the PKLot files are missing, recreate them:

```bash
cd Sightline_v5
python scripts/setup_pklot_sample.py --force
```

## Run the app locally

Use four terminal windows.

### Terminal 1: Start the RTSP server

```bash
cd Sightline_v5
mediamtx
```

### Terminal 2: Publish the sample image as an RTSP stream

```bash
cd Sightline_v5

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

### Terminal 3: Start the backend

```bash
cd Sightline_v5
source .venv/bin/activate

MODEL_PATH=yolov8n-obb.pt \
CONFIDENCE_THRESHOLD=0.15 \
IOU_THRESHOLD=0.20 \
.venv/bin/uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

The local app will try Postgres first. If Postgres is not running, it falls back to in-memory storage, which is fine for local testing. To skip the connection attempt entirely and silence the fallback warning, set `DATABASE_URL=memory`.

### Terminal 4: Start the frontend

```bash
cd Sightline_v5/frontend
npm run dev
```

Open the dashboard:

```text
http://localhost:5173
```

## Add the sample camera in the UI

In the dashboard:

1. Click `Add`.
2. Camera ID: `cam1`
3. Name: `Sample Lot 1`
4. RTSP URL: `rtsp://127.0.0.1:8554/sightline`
5. Click `Load PKLot`.

You should see 100 mapped parking spaces and live occupancy counts.

## Useful checks

Check that the RTSP stream is alive:

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
cd Sightline_v5
source .venv/bin/activate
pytest -q
```

Build the frontend:

```bash
cd Sightline_v5/frontend
npm run build
```

## Project layout

```text
backend/      FastAPI app, detector, RTSP camera manager, database service
frontend/     React dashboard and calibration UI
scripts/      Database schema and PKLot sample setup
docker/       Docker Compose, backend, frontend, and nginx files
tests/        Detector tests
sample-data/  Small PKLot fixture used for local testing
```
