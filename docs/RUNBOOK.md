# FaceLens operator runbook

## Components

| Component | Runs | Scales | State |
|---|---|---|---|
| Web (`node server.js`, Next.js standalone) | Node 22 | Horizontally, stateless | none |
| API (`facelens-api serve`) | FastAPI/uvicorn | Horizontally, stateless | none (runs the retention sweeper loop) |
| Worker (`celery -A facelens_api.jobs.worker:celery_app worker -Q inference`) | Celery | By queue depth | none |
| PostgreSQL | sessions/jobs metadata (no images) | managed (RDS/Cloud SQL) | 30-day metadata |
| Redis | Celery broker and rate-limit counters | managed (ElastiCache/Memorystore) | ephemeral |
| Object storage | sanitized uploads and generated images | managed (S3) | 1 h TTL + 1 day lifecycle backstop |

## Deploy (reference: AWS ECS Fargate; any container platform works)

1. **Bucket:** private, Block Public Access on, default encryption SSE-KMS, versioning **off** (versions would outlive deletion), and a lifecycle rule that expires all objects after **1 day**. Grant the API and worker task role `s3:GetObject`, `PutObject`, `DeleteObject`, and `ListBucket` on the prefix only.
2. **Secrets** (Secrets Manager, injected as env vars): `FACELENS_SIGNING_SECRET` (≥32 random chars), `FACELENS_DATABASE_URL`, and `FACELENS_REDIS_URL` (use `rediss://` in production).
3. **Required production settings** are enforced by `facelens-api check-config`: `storage_backend=s3`, `job_backend=celery`, `rate_limit_backend=redis`, `face_detector=yunet`, `allow_mock_models=false`, and SSE enabled. Mocks are refused, so **no feature can be enabled in production until a real, license-approved model is registered (Phase 4).**
4. **Migrations:** run `facelens-api migrate` as a one-off task before rolling out a new API version. Set `FACELENS_AUTO_MIGRATE=false` on all services in production.
5. **Routing (important):** at the load balancer, send `/v1/*` to the API target group and everything else to the web target group. The browser only ever calls its own origin. Don't rely on the web container's `/v1` rewrite in production: Next's proxy doesn't add `X-Forwarded-For`, so every user would share one rate-limit bucket. Set `FORWARDED_ALLOW_IPS` on the API to the load balancer's subnet so uvicorn trusts only its forwarding headers. Build the web image with `API_ORIGIN` pointing at the internal API address (used only as a fallback).
6. **Rollout:** API behind an ALB with TLS. Set the target health check to `/readyz`, liveness to `/healthz`, and the deregistration delay to ≥ 40 s. Run uvicorn with `--forwarded-allow-ips` set to the load balancer's addresses so rate limits see real client IPs. Enforce a request body limit of 11 MB at the load balancer or WAF too.
7. **Workers:** set `stop_timeout` to ≥ 120 s so Celery's warm shutdown can finish in-flight jobs. Autoscale on queue length.

**Timeouts.** With `job_backend=thread`, an inference call that exceeds `FACELENS_INFERENCE_TIMEOUT_SECONDS` fails the job, but Python can't kill the thread, so a hung model still holds a worker thread. That's why production uses Celery: its hard `task_time_limit` (3 × timeout + 30 s) kills and replaces the worker process.

## Rollback

Redeploy the previous image tag. Migrations are additive (new nullable columns). A downgrade (`alembic downgrade -1`) is only needed if a release note says so.

## Routine operations

| Task | How |
|---|---|
| Validate config | `facelens-api check-config` (exit 2 on error) |
| Force a retention sweep | `facelens-api sweep` |
| Refresh model files | `facelens-api fetch-models` (SHA-256 pinned in `ml/artifacts.py`) |
| Check health | `GET /readyz` → `database`, `storage`, `redis`, `retention_sweeper` |

## Data-subject and deletion requests

We hold no identity data, so we can't look anyone up by name or email. A user deletes their data with **Delete** in the UI (or `DELETE /v1/sessions/{id}`). Otherwise everything is removed automatically within the session TTL (default 1 h), with the bucket lifecycle rule as a backstop at 1 day. Remaining job metadata (model version, latency, error code) contains no image or face data and is purged after 30 days.

## Alerts (suggested)

- `/readyz` failing for > 2 min on any replica.
- `retention_sweeper` false: **treat as a privacy incident.** Images may be outliving their TTL.
- `job.finished` with `outcome=failed` above 5% over 10 min, grouped by `error_code` and `model_id`.
- Queue depth > 100 or p95 job latency > 20 s.
- Any 5xx `request.unhandled_error`.

## Incidents

1. **Suspected image exposure:** rotate `FACELENS_SIGNING_SECRET`, which invalidates all result links immediately. Run `facelens-api sweep`. Audit bucket access logs. Follow the privacy incident process.
2. **Model misbehaving:** turn the feature off with `FACELENS_FEATURE_<TASK>=false`. Clients see `feature_disabled`, and nothing falls back to a mock.
3. **Model file tampered or corrupted:** the service refuses to start (checksum mismatch). Re-run `fetch-models` from a trusted network and investigate.

## Logs

JSON on stdout, one event per line, each with a `request_id`. The logs never contain image bytes, filenames, tokens, signed-URL signatures or inference outputs. A redaction processor enforces this, and a test asserts it. Don't raise the log level to DEBUG in production.
