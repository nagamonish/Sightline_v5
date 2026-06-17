# CI Setup

The intended GitHub Actions workflow for Sightline is below.

GitHub requires the pushing token to include the `workflow` scope before files can be added under `.github/workflows`. The current local GitHub token does not have that scope, so this workflow is documented here until the token is refreshed.

To enable CI:

1. Refresh GitHub CLI auth with workflow permissions:

```bash
gh auth refresh -h github.com -s workflow
```

2. Create `.github/workflows/ci.yml`.
3. Copy the workflow below into that file.
4. Commit and push.

## Workflow

```yaml
name: CI

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

permissions:
  contents: read

jobs:
  backend-tests:
    name: Backend tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: backend/requirements.txt

      - name: Install backend dependencies
        run: python -m pip install -r backend/requirements.txt

      - name: Run backend tests
        env:
          PYTHONPATH: .
          MODEL_PATH: disabled
          DATABASE_URL: memory
        run: python -m pytest -q

  frontend-build:
    name: Frontend build
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install frontend dependencies
        working-directory: frontend
        run: npm ci

      - name: Build frontend
        working-directory: frontend
        run: npm run build
```
