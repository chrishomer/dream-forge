from __future__ import annotations

import hashlib
import json
import uuid as _uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update, String, cast
from sqlalchemy.orm import Session

from .models import Artifact, Event, Job, Step


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
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(job)
    step = Step(
        id=_uuid.uuid4(),
        job_id=job.id,
        name="generate",
        status="queued",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(step)
    session.flush()
    return job


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
        .values(status="running", started_at=datetime.utcnow(), updated_at=datetime.utcnow())
    )


def mark_step_finished(session: Session, step_id: _uuid.UUID, status: str) -> None:
    session.execute(
        update(Step)
        .where(cast(Step.id, String) == str(step_id))
        .values(status=status, finished_at=datetime.utcnow(), updated_at=datetime.utcnow())
    )


def mark_job_status(session: Session, job_id: _uuid.UUID, status: str, error: dict[str, Any] | None = None) -> None:
    values: dict[str, Any] = {"status": status, "updated_at": datetime.utcnow()}
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
        ts=datetime.utcnow(),
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
        created_at=datetime.utcnow(),
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
