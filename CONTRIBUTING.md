# Contributing

Sightline is proprietary software. This repository is public for review, demonstration, and portfolio visibility only.

Public contributions are not accepted unless the repository owner explicitly approves them in writing before the work begins.

## Before Opening A Pull Request

Do not open a pull request unless you have permission from Monish Munagala or an approved repository owner.

Approved contributors should:

1. Create an issue describing the intended change.
2. Wait for approval.
3. Keep the change focused.
4. Run backend tests.
5. Run the frontend build.
6. Update docs when behavior changes.

## Local Checks

Backend:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

Frontend:

```bash
cd frontend
npm run build
```

## Pull Request Expectations

Every approved pull request should include:

- A short summary.
- Testing notes.
- Screenshots or screen recordings for UI changes.
- Links to related issues.
- Notes for any known limitations.

## License

No contribution changes the proprietary license. By submitting approved work, you agree that the work may be used under this repository's proprietary terms.
