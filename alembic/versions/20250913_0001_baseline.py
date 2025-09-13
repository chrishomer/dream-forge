"""Baseline schema for jobs, steps, events, artifacts, models

Revision ID: 20250913_0001
Revises: 
Create Date: 2025-09-13 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250913_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("idempotency_key_hash", sa.LargeBinary(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('queued','running','succeeded','failed')", name="jobs_status_check"),
        sa.CheckConstraint("type in ('generate','model_download')", name="jobs_type_check"),
    )
    op.create_index("jobs_updated_idx", "jobs", ["updated_at"], unique=False)
    op.create_index("jobs_status_idx", "jobs", ["status"], unique=False)
    op.create_index("jobs_idempo_uniq", "jobs", ["idempotency_key_hash"], unique=True)

    op.create_table(
        "steps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('queued','running','succeeded','failed')", name="steps_status_check"),
    )
    op.create_index("steps_job_created_idx", "steps", ["job_id", "created_at"], unique=False)

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(length=36), sa.ForeignKey("steps.id", ondelete="CASCADE"), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("level", sa.String(), nullable=False, server_default="info"),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.CheckConstraint("level in ('debug','info','warn','error')", name="events_level_check"),
    )
    op.create_index("events_job_ts_desc_idx", "events", ["job_id", "ts"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(length=36), sa.ForeignKey("steps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("format", sa.String(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("item_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("format in ('png','jpg')", name="artifacts_format_check"),
        sa.CheckConstraint("width > 0 AND height > 0", name="artifacts_size_check"),
        sa.UniqueConstraint("job_id", "step_id", "item_index", name="artifacts_job_step_item_uniq"),
    )
    op.create_index("artifacts_job_idx", "artifacts", ["job_id"], unique=False)

    op.create_table(
        "models",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("checkpoint_hash", sa.String(), nullable=True),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("installed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("parameters_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("files_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("models_name_ver_kind_uniq", "models", ["name", "version", "kind"], unique=True)
    op.create_index("models_enabled_installed_idx", "models", ["enabled", "installed"], unique=False)
    op.create_index("models_source_uri_idx", "models", ["source_uri"], unique=False)


def downgrade() -> None:
    op.drop_index("models_source_uri_idx", table_name="models")
    op.drop_index("models_enabled_installed_idx", table_name="models")
    op.drop_index("models_name_ver_kind_uniq", table_name="models")
    op.drop_table("models")

    op.drop_index("artifacts_job_idx", table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_index("events_job_ts_desc_idx", table_name="events")
    op.drop_table("events")

    op.drop_index("steps_job_created_idx", table_name="steps")
    op.drop_table("steps")

    op.drop_index("jobs_idempo_uniq", table_name="jobs")
    op.drop_index("jobs_status_idx", table_name="jobs")
    op.drop_index("jobs_updated_idx", table_name="jobs")
    op.drop_table("jobs")

