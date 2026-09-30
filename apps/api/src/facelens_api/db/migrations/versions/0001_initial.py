"""initial schema: sessions and jobs

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from facelens_api.db.models import UTCDateTime

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("ended_at", UTCDateTime(), nullable=True),
        sa.Column("image_key", sa.String(200), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("source_format", sa.String(8), nullable=True),
        sa.Column("consent_version", sa.String(16), nullable=False),
    )
    op.create_index("ix_sessions_status_expires", "sessions", ["status", "expires_at"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(40),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("result_key", sa.String(200), nullable=True),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("model_version", sa.String(32), nullable=True),
        sa.Column("is_mock", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
    )
    op.create_index("ix_jobs_session_id", "jobs", ["session_id"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_session_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_sessions_status_expires", table_name="sessions")
    op.drop_table("sessions")
