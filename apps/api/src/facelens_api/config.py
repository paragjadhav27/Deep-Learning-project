"""Service configuration, validated once at startup.

Every setting is read from environment variables prefixed with ``FACELENS_``.
Invalid or unsafe combinations fail fast instead of running half-configured.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-insecure-signing-secret-change-me"  # noqa: S105 - rejected outside dev/test


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FACELENS_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # Persistence
    database_url: str = "sqlite:///./var/facelens.db"
    auto_migrate: bool = True
    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: Path = Path("./var/blobs")
    # S3-compatible object storage (private bucket, SSE, lifecycle rule; see docs/RUNBOOK.md)
    s3_bucket: str | None = None
    s3_prefix: str = "facelens"
    s3_region: str | None = None
    s3_endpoint_url: str | None = None  # e.g. SeaweedFS in docker-compose
    s3_sse: Literal["AES256", "aws:kms", "none"] = "AES256"
    s3_kms_key_id: str | None = None

    # Shared state for multi-process deployments (Celery broker, rate limits)
    redis_url: str | None = None

    # Retention (see docs/PLAN.md section 6)
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    metadata_retention_days: int = Field(default=30, ge=1, le=365)
    sweep_interval_seconds: int = Field(default=300, ge=5, le=3600)
    sweeper_enabled: bool = True

    # Upload limits
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    min_image_side: int = Field(default=128, ge=32)
    max_image_side: int = Field(default=4096, le=12_000)

    # Abuse controls (per client IP, per minute)
    rate_limit_uploads_per_minute: int = Field(default=10, ge=1)
    rate_limit_jobs_per_minute: int = Field(default=30, ge=1)
    rate_limit_backend: Literal["memory", "redis"] = "memory"

    # Jobs. "sync" runs inference inside the request: local demos and tests only.
    job_backend: Literal["thread", "sync", "celery"] = "thread"
    job_workers: int = Field(default=2, ge=1, le=32)
    inference_timeout_seconds: float = Field(default=30.0, gt=0, le=600)

    # Face detection (YuNet, MIT). "none" skips face checks: local UI work only.
    face_detector: Literal["yunet", "none"] = "yunet"
    model_dir: Path = Path("./models")
    face_score_threshold: float = Field(default=0.7, ge=0.3, le=0.99)
    min_face_side: int = Field(default=64, ge=16)

    # Features and model policy
    feature_age_estimation: bool = True
    feature_presentation_estimation: bool = True
    feature_age_transformation: bool = True
    allow_mock_models: bool = True
    aging_allow_young_targets: bool = False  # requires legal review; see PLAN section 7.4
    # Which provider serves each tool. Real models need the `ml` extra and fetched weights.
    age_model: Literal["mock", "mivolo_v2"] = "mock"
    presentation_model: Literal["mock", "mivolo_v2"] = "mock"
    aging_model: Literal["mock", "sam"] = "mock"  # SAM: ~2.2 GB RAM, ~5-20 s/image on CPU
    torch_threads: int = Field(default=2, ge=1, le=64)
    # Deployment license scope. "commercial" (the strict default) refuses models whose
    # license only permits non-commercial use.
    license_scope: Literal["commercial", "non_commercial"] = "commercial"
    # Serve real models that haven't passed the evaluation gates. Local experiments only.
    allow_ungated_models: bool = False

    # Security
    signing_secret: SecretStr = SecretStr(_DEV_SECRET)
    result_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("signing_secret", mode="before")
    @classmethod
    def _empty_secret_is_unset(cls, v: object) -> object:
        # `FACELENS_SIGNING_SECRET=` (as in .env.example) must never mean an empty HMAC key.
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        return SecretStr(_DEV_SECRET) if raw in ("", None) else v

    @model_validator(mode="after")
    def _validate_combinations(self) -> Settings:
        if self.min_image_side >= self.max_image_side:
            raise ValueError("min_image_side must be smaller than max_image_side")
        if self.environment in ("staging", "production"):
            secret = self.signing_secret.get_secret_value()
            if secret == _DEV_SECRET or len(secret) < 32:
                raise ValueError("FACELENS_SIGNING_SECRET must be set to >=32 random chars")
            if self.job_backend == "sync":
                raise ValueError("job_backend=sync is for local demos only")
            if self.allow_ungated_models:
                raise ValueError("allow_ungated_models is for local experiments only")
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("storage_backend=s3 requires FACELENS_S3_BUCKET")
        if self.s3_sse == "aws:kms" and not self.s3_kms_key_id:
            raise ValueError("s3_sse=aws:kms requires FACELENS_S3_KMS_KEY_ID")
        needs_redis = self.job_backend == "celery" or self.rate_limit_backend == "redis"
        if needs_redis and not self.redis_url:
            raise ValueError("celery jobs / redis rate limiting require FACELENS_REDIS_URL")
        if self.environment == "production":
            problems = {
                "Mock models cannot be enabled in production": self.allow_mock_models,
                "Use PostgreSQL in production": self.database_url.startswith("sqlite"),
                "Use object storage (s3) in production": self.storage_backend != "s3",
                "Use celery jobs in production": self.job_backend != "celery",
                "Use redis rate limiting in production": self.rate_limit_backend != "redis",
                "Face detection is required in production": self.face_detector != "yunet",
                "Unencrypted object storage is not allowed": self.s3_sse == "none",
            }
            failed = [msg for msg, bad in problems.items() if bad]
            if failed:
                raise ValueError("; ".join(failed))
        return self

    @property
    def is_dev_like(self) -> bool:
        return self.environment in ("development", "test")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
