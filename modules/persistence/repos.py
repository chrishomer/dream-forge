from __future__ import annotations

import hashlib
import json
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, String, cast
from sqlalchemy.orm import Session

from .models import Artifact, Event, Job, Step, Model
UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _hash_idempotency(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def create_job_with_step(
    session: Session,
    *,
    job_type: str,
    params: dict[str, Any],
    idempotency_key: str | None,
) -> Job:
    job = Job(
        id=_uuid.uuid4(),
        type=job_type,
        status="queued",
        params_json=params,
        idempotency_key_hash=_hash_idempotency(idempotency_key) if idempotency_key else None,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(job)
    step = Step(
        id=_uuid.uuid4(),
        job_id=job.id,
        name="generate",
        status="queued",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(step)
    session.flush()
    return job


def create_job_with_chain(
    session: Session,
    *,
    job_type: str,
    params: dict[str, Any],
    idempotency_key: str | None,
    upscale_scale: int = 2,
    upscale_impl: str | None = None,
    upscale_strict_scale: bool | None = None,
) -> Job:
    """Create a job with two ordered steps: generate -> upscale.

    Stores minimal per-step metadata in Step.metadata_json for traceability.
    """
    job = Job(
        id=_uuid.uuid4(),
        type=job_type,
        status="queued",
        params_json=params,
        idempotency_key_hash=_hash_idempotency(idempotency_key) if idempotency_key else None,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(job)

    step_gen = Step(
        id=_uuid.uuid4(),
        job_id=job.id,
        name="generate",
        status="queued",
        metadata_json={},
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(step_gen)

    step_up = Step(
        id=_uuid.uuid4(),
        job_id=job.id,
        name="upscale",
        status="queued",
        metadata_json={
            "scale": int(upscale_scale),
            **({"impl": upscale_impl} if upscale_impl else {}),
            **({"strict_scale": bool(upscale_strict_scale)} if upscale_strict_scale is not None else {}),
        },
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(step_up)

    session.flush()
    return job


def get_step_by_name(session: Session, *, job_id: str | _uuid.UUID, name: str) -> Step | None:
    jid = str(job_id)
    return session.scalars(
        select(Step).where(cast(Step.job_id, String) == jid, Step.name == name).order_by(Step.created_at.asc())
    ).first()


def get_job(session: Session, job_id: str | _uuid.UUID) -> Job | None:
    # Avoid dialect-dependent UUID casting by comparing as text
    jid = str(job_id)
    return session.scalars(select(Job).where(cast(Job.id, String) == jid)).first()


def get_job_with_steps(session: Session, job_id: str | _uuid.UUID) -> tuple[Job | None, list[Step]]:
    job = get_job(session, job_id)
    if not job:
        return None, []
    steps = session.scalars(select(Step).where(cast(Step.job_id, String) == str(job.id)).order_by(Step.created_at.asc())).all()
    return job, list(steps)


def list_jobs(session: Session, *, status: str | None = None, limit: int = 20) -> list[Job]:
    """List recent jobs ordered by updated_at desc with optional status filter.

    Caps limit to 200 to avoid accidental large scans.
    """
    lmt = max(1, min(int(limit), 200))
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    stmt = stmt.order_by(Job.updated_at.desc()).limit(lmt)
    return list(session.scalars(stmt).all())

def list_jobs(session: Session, *, status: str | None = None, limit: int = 20) -> list[Job]:
    """List recent jobs ordered by updated_at desc with optional status filter.

    Caps limit to 200 to avoid accidental large scans.
    """
    lmt = max(1, min(int(limit), 200))
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    stmt = stmt.order_by(Job.updated_at.desc()).limit(lmt)
    return list(session.scalars(stmt).all())


def list_artifacts_by_job(session: Session, job_id: str | _uuid.UUID) -> list[Artifact]:
    jid = str(job_id)
    rows = session.scalars(
        select(Artifact)
        .where(cast(Artifact.job_id, String) == jid)
        .order_by(Artifact.item_index.asc(), Artifact.created_at.asc())
    ).all()
    return list(rows)


def iter_events(
    session: Session,
    job_id: str | _uuid.UUID,
    *,
    since_ts: datetime | None = None,
    tail: int | None = None,
) -> list[Event]:
    jid = str(job_id)
    stmt = select(Event).where(cast(Event.job_id, String) == jid)
    if since_ts is not None:
        stmt = stmt.where(Event.ts >= since_ts)
        stmt = stmt.order_by(Event.ts.asc())
        return list(session.scalars(stmt).all())

    # Tail without since: fetch last N by ts desc, then reverse in memory
    stmt = stmt.order_by(Event.ts.desc())
    if tail is not None and tail > 0:
        stmt = stmt.limit(int(tail))
    out = list(session.scalars(stmt).all())
    out.reverse()
    return out


def progress_for_job(session: Session, job_id: str | _uuid.UUID) -> float:
    job = get_job(session, job_id)
    if not job:
        return 0.0
    # Minimal aggregation per M2 plan
    if job.status == "succeeded":
        return 1.0
    if job.status == "failed":
        # Leave last known progress (approximate via events presence)
        evts = iter_events(session, job_id, since_ts=None, tail=None)
        has_artifact = any(e.code == "artifact.written" for e in evts)
        return 0.9 if has_artifact else 0.5 if any(e.code == "step.start" for e in evts) else 0.0
    if job.status == "running":
        evts = iter_events(session, job_id, since_ts=None, tail=None)
        return 0.9 if any(e.code == "artifact.written" for e in evts) else 0.5
    # queued
    return 0.0


def mark_step_running(session: Session, step_id: _uuid.UUID) -> None:
    session.execute(
        update(Step)
        .where(cast(Step.id, String) == str(step_id))
        .values(status="running", started_at=_utcnow(), updated_at=_utcnow())
    )


def mark_step_finished(session: Session, step_id: _uuid.UUID, status: str) -> None:
    session.execute(
        update(Step)
        .where(cast(Step.id, String) == str(step_id))
        .values(status=status, finished_at=_utcnow(), updated_at=_utcnow())
    )


def mark_job_status(session: Session, job_id: _uuid.UUID, status: str, error: dict[str, Any] | None = None) -> None:
    values: dict[str, Any] = {"status": status, "updated_at": _utcnow()}
    if error:
        values["error_code"] = error.get("code")
        values["error_message"] = json.dumps(error)
    session.execute(update(Job).where(cast(Job.id, String) == str(job_id)).values(**values))


def append_event(
    session: Session,
    *,
    job_id: _uuid.UUID,
    step_id: _uuid.UUID | None,
    code: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
) -> Event:
    evt = Event(
        id=_uuid.uuid4(),
        job_id=job_id,
        step_id=step_id,
        ts=_utcnow(),
        code=code,
        level=level,
        payload_json=payload or {},
    )
    session.add(evt)
    session.flush()
    return evt


def insert_artifact(
    session: Session,
    *,
    job_id: _uuid.UUID,
    step_id: _uuid.UUID,
    format: str,
    width: int,
    height: int,
    seed: int | None,
    item_index: int,
    s3_key: str,
    checksum: str | None,
    metadata_json: dict[str, Any] | None = None,
) -> Artifact:
    art = Artifact(
        id=_uuid.uuid4(),
        job_id=job_id,
        step_id=step_id,
        created_at=_utcnow(),
        format=format,
        width=width,
        height=height,
        seed=seed,
        item_index=item_index,
        s3_key=s3_key,
        checksum=checksum,
        metadata_json=metadata_json or {},
    )
    session.add(art)
    session.flush()
    return art


# --- Models (Registry) ---

def list_models(session: Session, *, enabled_only: bool = True) -> list[Model]:
    stmt = select(Model)
    if enabled_only:
        # Use integer semantics (0/1) for cross-dialect compatibility
        stmt = stmt.where(Model.enabled == 1).where(Model.installed == 1)
    rows = session.scalars(stmt.order_by(Model.created_at.asc())).all()
    return list(rows)


def get_model(session: Session, model_id: str | _uuid.UUID) -> Model | None:
    mid = str(model_id)
    return session.scalars(select(Model).where(cast(Model.id, String) == mid)).first()


def get_model_by_key(session: Session, *, name: str, version: str | None, kind: str) -> Model | None:
    stmt = select(Model).where(Model.name == name, Model.kind == kind)
    if version is None:
        stmt = stmt.where(Model.version.is_(None))
    else:
        stmt = stmt.where(Model.version == version)
    return session.scalars(stmt).first()


def upsert_model(
    session: Session,
    *,
    name: str,
    kind: str,
    version: str | None,
    source_uri: str | None,
    checkpoint_hash: str | None = None,
    parameters_schema: dict | None = None,
    capabilities: list[str] | None = None,
) -> Model:
    existing = get_model_by_key(session, name=name, version=version, kind=kind)
    now = _utcnow()
    if existing:
        existing.source_uri = source_uri
        existing.checkpoint_hash = checkpoint_hash
        if parameters_schema is not None:
            existing.parameters_schema = parameters_schema
        if capabilities is not None:
            existing.capabilities = capabilities
        existing.updated_at = now
        session.flush()
        return existing

    m = Model(
        id=_uuid.uuid4(),
        name=name,
        kind=kind,
        version=version,
        source_uri=source_uri,
        checkpoint_hash=checkpoint_hash,
        parameters_schema=parameters_schema or {},
        capabilities=capabilities or ["generate"],
        installed=False,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    session.add(m)
    session.flush()
    return m


def mark_model_installed(
    session: Session,
    *,
    model_id: _uuid.UUID,
    local_path: str,
    files_json: list[dict],
    installed: bool = True,
) -> None:
    session.execute(
        update(Model)
        .where(cast(Model.id, String) == str(model_id))
        .values(local_path=local_path, files_json=files_json, installed=1 if installed else 0, updated_at=_utcnow())
    )


def set_model_enabled(session: Session, *, model_id: _uuid.UUID, enabled: bool) -> None:
    session.execute(
        update(Model)
        .where(cast(Model.id, String) == str(model_id))
        .values(enabled=1 if enabled else 0, updated_at=_utcnow())
    )


def get_default_model(session: Session, *, kind: str = "sdxl-checkpoint") -> Model | None:
    stmt = (
        select(Model)
        .where(Model.kind == kind, Model.enabled == 1, Model.installed == 1)
        .order_by(Model.created_at.asc())
    )
    return session.scalars(stmt).first()
