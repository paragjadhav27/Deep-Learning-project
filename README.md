# FaceLens

Privacy-first web app with three **illustrative, opt-in** face-image tools: age estimation, perceived-presentation estimation, and age-transformation previews. None of them is suitable for identification or any consequential decision.

- Product and technical plan: [docs/PLAN.md](docs/PLAN.md)
- Model cards and measured results: [docs/MODEL_CARDS.md](docs/MODEL_CARDS.md)
- Operations: [docs/RUNBOOK.md](docs/RUNBOOK.md)
- API service: [apps/api](apps/api/README.md)
- Web app: [apps/web](apps/web/README.md)
- Evaluation: [eval](eval/README.md)

**Status:** Face detection is real (YuNet, MIT). Each tool can run on a real model (MiVOLO v2 for age and presentation, SAM for age transformation) or on a **mock**. Mocks are the default, and the API and UI label them as mocks. The real models haven't passed their release gates (see the model cards), so they only run in local experiments.

## Repository layout

| Path | What it is |
|---|---|
| `apps/api` | FastAPI service, Celery worker, model providers, migrations, tests |
| `apps/web` | Next.js 16 web app, Vitest and Playwright tests |
| `eval` | Evaluation harness (FairFace) and committed reports |
| `ops/loadtest.py` | Load test against a running API |
| `docs` | Plan, model cards, runbook |
| `docker-compose.yml` | Local stack with the production topology |

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker Desktop | recent | Option A (Docker Compose) |
| Python | 3.12 (3.11 works) | Option B, tests, evaluation |
| Node.js | 22 | Option B, web tests |
| Git | any | cloning |

The commands below are for **PowerShell on Windows**. On macOS or Linux, use `source .venv/bin/activate` instead of `.venv\Scripts\Activate.ps1`, and `cp` instead of `Copy-Item`.

---

## Option A: run everything with Docker Compose

This starts the web app, API, Celery worker, PostgreSQL, Redis, and SeaweedFS (a local S3 stand-in). The tools use mock estimators with real face detection.

```powershell
# From the repo root, with Docker Desktop running
docker compose up --build -d      # first build takes 10+ minutes (PyTorch)
docker compose ps                 # wait until api and web are "healthy"
```

Open http://localhost:3000. The API docs are at http://localhost:8000/docs.

| Task | Command |
|---|---|
| Follow logs | `docker compose logs -f api worker web` |
| Restart one service | `docker compose restart api` |
| Rebuild after code changes | `docker compose up --build -d` |
| Stop the stack | `docker compose down` |
| Stop and delete the database volume | `docker compose down -v` |
| Validate the compose file | `docker compose config --quiet` |

To bake the SAM weights (2.2 GB) into the image, build with `docker compose build --build-arg MODELS=yunet-2026may,mivolo-v2,sam-ffhq-aging`. SAM needs about 2.2 GB of RAM per process, and the API and worker each load a copy, so it usually doesn't fit in Docker Desktop's default memory. Use Option B to run SAM.

---

## Option B: run locally without Docker

Uses SQLite and local file storage, so it needs no other services. Docker Compose also uses ports 3000 and 8000, so stop it first (`docker compose down`).

### 1. API (terminal 1)

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install with CPU-only PyTorch (needed for the real models and the test suite)
pip install -e ".[dev]" --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple

# Download pinned model weights and verify their SHA-256
facelens-api fetch-models --only yunet-2026may,mivolo-v2      # small; add ,sam-ffhq-aging for SAM (2.2 GB)

Copy-Item ..\..\.env.example .env    # optional; the defaults work for development
facelens-api check-config
facelens-api serve --reload          # http://127.0.0.1:8000/docs
```

For a minimal install without PyTorch (mock estimators only), use `pip install -e .` and `facelens-api fetch-models --only yunet-2026may`.

### 2. Web app (terminal 2)

```powershell
cd apps/web
npm ci
npm run dev                          # http://localhost:3000; /v1/* is proxied to the API
```

Open http://localhost:3000.

To run a production build of the web app instead:

```powershell
npm run build
npm run start
```

### 3. Optional: use the real models

Add these lines to `apps/api/.env`, then restart the API. They require the `ml` extra (included in `.[dev]`) and the matching weights from `fetch-models`.

```ini
FACELENS_AGE_MODEL=mivolo_v2
FACELENS_PRESENTATION_MODEL=mivolo_v2
FACELENS_AGING_MODEL=sam                 # needs sam-ffhq-aging weights and ~2.2 GB RAM
FACELENS_LICENSE_SCOPE=non_commercial    # MiVOLO and SAM weights are non-commercial
FACELENS_ALLOW_UNGATED_MODELS=true       # they haven't passed the release gates; refused in production
FACELENS_TORCH_THREADS=4
FACELENS_INFERENCE_TIMEOUT_SECONDS=120   # SAM takes ~5-20 s per image on CPU
```

`GET http://127.0.0.1:8000/v1/models` shows which provider serves each tool and whether it's a mock.

---

## Tests and checks

### API

```powershell
cd apps/api
.venv\Scripts\Activate.ps1
ruff check .
ruff format --check .
mypy
pytest
facelens-api export-openapi --check     # fails if apps/api/openapi.json is out of date
```

Set `FACELENS_TEST_REQUIRE_MODELS=1` to make missing model weights fail tests instead of skipping them. Set `FACELENS_TEST_POSTGRES_URL` to also run the tests against PostgreSQL.

### Web

```powershell
cd apps/web
npm run typecheck
npm run lint
npm test                    # Vitest unit and component tests
npm run check:api           # generated API types match apps/api/openapi.json
```

### End-to-end (Playwright)

Starts the real API from `apps/api/.venv` and a production build of the web app. Needs the API venv and the YuNet weights from Option B, step 1.

```powershell
cd apps/web
npx playwright install chromium
npm run test:e2e
```

### After changing the API schema

```powershell
cd apps/api; facelens-api export-openapi     # writes apps/api/openapi.json
cd ../web;   npm run gen:api                 # regenerates src/lib/api/schema.d.ts
```

---

## API operator commands

Run from `apps/api` with the venv active.

| Command | Purpose |
|---|---|
| `facelens-api serve [--host] [--port] [--reload]` | Run the API server |
| `facelens-api check-config` | Validate configuration and exit (non-zero on error) |
| `facelens-api migrate` | Apply database migrations |
| `facelens-api sweep` | Run one retention sweep now |
| `facelens-api fetch-models [--dir DIR] [--only a,b]` | Download pinned model files and verify SHA-256 |
| `facelens-api export-openapi [--out FILE] [--check]` | Write or check the OpenAPI schema |
| `celery -A facelens_api.jobs.worker:celery_app worker -Q inference` | Inference worker (with `FACELENS_JOB_BACKEND=celery` and Redis) |

All settings are environment variables prefixed with `FACELENS_`. See [.env.example](.env.example).

---

## Evaluation

Measures the production code path on the FairFace validation split. Details and method: [eval/README.md](eval/README.md).

```powershell
# 1. Download the data (pinned revision)
New-Item -ItemType Directory -Force eval/.data
curl.exe -L -o eval/.data/fairface_val_1.25.parquet "https://huggingface.co/datasets/HuggingFaceM4/FairFace/resolve/54d573cdb8b5af490ba8da9da2799628f6e5c496/1.25/validation-00000-of-00001-09e3e67bb00ab4ec.parquet"
Get-FileHash eval/.data/fairface_val_1.25.parquet   # ce47863c011f355ef7ab63d70420d9d4b36fce03cf1621a26597955da21968bb

# 2. Install the eval extra (from apps/api, venv active) and fetch weights
pip install -e ".[eval]" --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
facelens-api fetch-models

# 3. From the repo root
python eval/run_eval.py predict                       # ~2 CPU-hours, resumable
python eval/run_eval.py analyze --write-calibration
python eval/run_aging_eval.py --per-group 20 --write-gate   # SAM aging gates (after predict)
python eval/dashboard.py                              # rebuild data for GET /v1/evaluations
python eval/dashboard.py --check                      # fail if the packaged file is out of date
```

---

## Load test

Start an API with high rate limits, otherwise you measure the rate limiter:

```powershell
cd apps/api
$env:FACELENS_RATE_LIMIT_UPLOADS_PER_MINUTE="100000"
$env:FACELENS_RATE_LIMIT_JOBS_PER_MINUTE="100000"
facelens-api serve
```

Then, from the repo root in another terminal (with the API venv active):

```powershell
python ops/loadtest.py --base http://127.0.0.1:8000 --users 10 --duration 60 --task age_estimation --image apps/web/e2e/fixtures/portrait.jpg
```

---

## Troubleshooting

- **Port 3000 or 8000 already in use.** Docker Compose and the local setup use the same ports, so only run one at a time. After stopping `npm run dev`, a leftover `node` process can keep port 3000; find it with `Get-NetTCPConnection -LocalPort 3000` and stop it.
- **`.venv\Scripts\Activate.ps1` is blocked.** Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
- **Docker build fails on a network or DNS error.** The API image downloads PyTorch and model weights. Retry the build.
- **Vitest or the build fails with `Cannot find native binding`.** Regenerate the lockfile: delete `node_modules` and `package-lock.json` in `apps/web`, then run `npm install`.
- **The API refuses to start with a model or license error.** Real models need `FACELENS_LICENSE_SCOPE=non_commercial` and `FACELENS_ALLOW_UNGATED_MODELS=true`, plus the weights from `fetch-models`. A checksum mismatch means a corrupted download: delete the file in `apps/api/models` and fetch it again.
