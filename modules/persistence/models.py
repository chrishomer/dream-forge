from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import CHAR, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> _uuid.UUID:  # pragma: no cover
    return _uuid.uuid4()


class GUID(TypeDecorator):
    """Platform-independent GUID/UUID type.

    Uses PostgreSQL's UUID type, otherwise stores as CHAR(36).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))  # type: ignore[attr-defined]
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None:
            return value
        if isinstance(value, _uuid.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None:
            return value
        return _uuid.UUID(str(value))


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[_uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid_pk)
    type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("status in ('queued','running','succeeded','failed')", name="jobs_status_check"),
        CheckConstraint("type in ('generate','model_download')", name="jobs_type_check"),
        Index("jobs_updated_idx", "updated_at"),
        Index("jobs_status_idx", "status"),
        # SQLite lacks partial indexes; we enforce uniqueness at app level there.
        Index("jobs_idempo_uniq", "idempotency_key_hash", unique=True),
    )


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[_uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid_pk)
    job_id: Mapped[_uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    job: Mapped[Job] = relationship("Job", backref="steps")

    __table_args__ = (
        CheckConstraint("status in ('queued','running','succeeded','failed')", name="steps_status_check"),
        Index("steps_job_created_idx", "job_id", "created_at"),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[_uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid_pk)
    job_id: Mapped[_uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[_uuid.UUID | None] = mapped_column(GUID(), ForeignKey("steps.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[str] = mapped_column(String, nullable=False, default="info")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("level in ('debug','info','warn','error')", name="events_level_check"),
        Index("events_job_ts_desc_idx", "job_id", "ts"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[_uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid_pk)
    job_id: Mapped[_uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[_uuid.UUID] = mapped_column(GUID(), ForeignKey("steps.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("format in ('png','jpg')", name="artifacts_format_check"),
        CheckConstraint("width > 0 AND height > 0", name="artifacts_size_check"),
        UniqueConstraint("job_id", "step_id", "item_index", name="artifacts_job_step_item_uniq"),
        Index("artifacts_job_idx", "job_id"),
    )


class Model(Base):
    __tablename__ = "models"

    id: Mapped[_uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid_pk)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str | None] = mapped_column(String)
    checkpoint_hash: Mapped[str | None] = mapped_column(String)
    source_uri: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    installed: Mapped[bool] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Integer, default=1, nullable=False)
    parameters_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    files_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("models_name_ver_kind_uniq", "name", "version", "kind", unique=True),
        Index("models_enabled_installed_idx", "enabled", "installed"),
        Index("models_source_uri_idx", "source_uri"),
    )
