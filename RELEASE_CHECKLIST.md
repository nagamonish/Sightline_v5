# Release Checklist

Use this checklist before tagging a version, sharing the repo, or demoing Sightline.

## Repo State

- [ ] Working tree is clean.
- [ ] Current branch is pushed.
- [ ] README is accurate.
- [ ] Changelog has a new entry.
- [ ] Roadmap reflects current priorities.
- [ ] Proprietary license and notice are present.

## Tests And Builds

- [ ] Backend tests pass with `PYTHONPATH=. .venv/bin/pytest -q`.
- [ ] Frontend build passes with `npm run build`.
- [ ] GitHub Actions CI passes.
- [ ] Docker build has been checked if Docker files changed.

## Local Demo

- [ ] MediaMTX starts.
- [ ] FFmpeg publishes the sample stream.
- [ ] Backend starts cleanly.
- [ ] Frontend opens at `http://localhost:5173`.
- [ ] `Load PKLot` works.
- [ ] Dashboard shows 100 spaces.
- [ ] MJPEG stream renders.
- [ ] WebSocket status shows connected.

## Security And Privacy

- [ ] No secrets are committed.
- [ ] No private RTSP URLs are committed.
- [ ] No private camera footage is committed.
- [ ] `.env.example` contains only safe example values.
- [ ] Security policy is present.

## Documentation

- [ ] Local setup instructions are current.
- [ ] Troubleshooting guide includes recent issues.
- [ ] API examples still work.
- [ ] Architecture doc matches the current system.
- [ ] Model card limitations are current.
- [ ] Dataset notice covers any included sample data.

## Release Notes

- [ ] Summarize what changed.
- [ ] Mention known limitations.
- [ ] Mention required environment variables.
- [ ] Mention migration steps if database schema changed.
- [ ] Link to important GitHub issues.
