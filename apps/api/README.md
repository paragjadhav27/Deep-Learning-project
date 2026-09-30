# FaceLens API

FastAPI service for the FaceLens tools. It handles upload validation and sanitization, short-lived sessions, inference jobs behind versioned model interfaces, and retention enforcement.

> **Mock models.** Face detection is real (YuNet, MIT, SHA-256 pinned). The three estimators are *mock* providers. They return placeholder values unrelated to the image and are marked `is_mock: true` in every response and in `GET /v1/models`. Configuration validation refuses mocks in production. See [docs/PLAN.md §7](../../docs/PLAN.md) for model selection status.

## Quick start (local, no Docker)

```bash
cd apps/api
python -m venv .venv
.venv/Scripts/activate            # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
facelens-api fetch-models         # downloads pinned YuNet weights (~230 KB), verifies SHA-256
cp ../../.env.example .env        # optional; defaults work for development
facelens-api serve --reload       # http://127.0.0.1:8000/docs
```

SQLite (`./var/facelens.db`) and local blob storage (`./var/blobs`) are created automatically, and migrations run on startup when `FACELENS_AUTO_MIGRATE=true`.

## Checks

```bash
ruff check . && ruff format --check .
mypy
pytest
```

## Operator commands

| Command | Purpose |
|---|---|
| `facelens-api check-config` | Validate environment configuration and exit (non-zero on error) |
| `facelens-api migrate` | Apply database migrations |
| `facelens-api sweep` | Run one retention sweep immediately |
| `facelens-api serve` | Run the server (graceful shutdown: 30 s) |
| `facelens-api fetch-models [--dir]` | Download pinned model files and verify SHA-256 |
| `celery -A facelens_api.jobs.worker:celery_app worker -Q inference` | Inference worker (`FACELENS_JOB_BACKEND=celery`) |

## Endpoints (v1)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/sessions` | multipart: `image`, `consent` (JSON). Returns `session_token` **once** |
| `GET` | `/v1/sessions/{id}` | header `X-Session-Token` |
| `DELETE` | `/v1/sessions/{id}` | Deletes the upload, generated images, and results immediately |
| `POST` | `/v1/sessions/{id}/jobs` | `{"task": "age_estimation" \| "presentation_estimation" \| "age_transformation", "params"?: {"target_age_group": ...}}` |
| `GET` | `/v1/jobs/{id}` | Poll status/progress/result |
| `DELETE` | `/v1/jobs/{id}` | Best-effort cancel |
| `GET` | `/v1/results/{job_id}/image?exp&sig` | Signed URL, 5-minute lifetime |
| `GET` | `/v1/models` | Feature flags, model cards, target-group availability |
| `GET` | `/healthz`, `/readyz` | Liveness; readiness (DB, storage, sweeper) |

## Privacy guarantees enforced in code

- Uploads must contain **exactly one** face at least 64 px wide (`no_face_detected`, `multiple_faces_detected`, `face_too_small`). The check runs before anything is stored.
- The content type is sniffed from magic bytes. Only JPEG, PNG, and WebP are accepted. Dimensions are checked from the header before decoding.
- Images are re-encoded from pixels, which drops EXIF/GPS, XMP, ICC, and trailing bytes. Original bytes and filenames are never stored.
- Logs pass through a redaction processor. Tests assert that no filename, token, signature, or result value appears in them.
- Session IDs, job IDs, and result images all require the session token or a short-lived HMAC signature. Every failure returns the same `404` to prevent probing.
- Sessions expire after `FACELENS_SESSION_TTL_SECONDS` (default 1 h). Access is refused at expiry, and the sweeper deletes blobs. Non-image job metadata is purged after `FACELENS_METADATA_RETENTION_DAYS` (default 30).
