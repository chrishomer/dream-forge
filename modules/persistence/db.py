from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import Engine

from .models import Base


def _db_url() -> str:
    url = os.getenv("DF_DB_URL")
    if url:
        return url
    # Fallback for local dev/tests without Postgres
    os.makedirs("db", exist_ok=True)
    return "sqlite+pysqlite:///db/dev.sqlite3"


_ENGINE: Engine = create_engine(_db_url(), future=True)

# For SQLite fallback in dev/tests, auto-create tables so tests can run without Alembic
if _ENGINE.url.get_backend_name().startswith("sqlite"):
    Base.metadata.create_all(_ENGINE)
SessionLocal = sessionmaker(
    bind=_ENGINE,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
    class_=Session,
)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()
