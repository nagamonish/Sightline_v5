# Roadmap

This roadmap tracks the next useful improvements for Sightline.

## Near Term

- Rename remaining ParkIQ references to Sightline.
- Fix the Docker model path and sample data setup.
- Make `POST /cameras` preserve existing calibrated slots.
- Make backend tests run with plain `pytest`.
- Improve local setup and fallback database behavior.

## Detection And Calibration

- Share one YOLO model instance across camera workers.
- Add frame-rate controls for inference.
- Use actual frame dimensions for homography defaults.
- Add point picking for homography setup.
- Improve auto-calibration for angled and partially occupied lots.

## Analytics

- Store state intervals, not only state-change events.
- Add time-weighted hourly occupancy.
- Add per-slot dwell time and turnover metrics.
- Add exportable CSV reports.

## Operations

- Add CI for Python tests and frontend build.
- Add production CORS configuration.
- Add deployment documentation.
- Add health checks for RTSP, model loading, database, and WebSocket broadcast.

## Product

- Add camera groups and multi-lot views.
- Add user roles.
- Add saved calibration versions.
- Add alerts for full lots, stale camera feeds, and reconnect storms.
