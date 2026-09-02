"""SQLAlchemy engine, session, and declarative base for Postgres-backed storage."""
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.config import settings

Base = declarative_base()

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """Lazily create the SQLAlchemy engine on first use.

    Deferred so importing this module (or anything that imports it, e.g.
    src/postgres_api.py, which src/agent.py imports unconditionally) doesn't
    require DATABASE_URL to be set — only actually using Postgres-backed
    storage does. See Documentation/ARCHITECTURE_DECISIONS.md, I1.
    """
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Set it in .env (see .env.example) before "
                "using Postgres-backed storage (PostgresAPI / PostgresRollbackStorage)."
            )
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def _get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _session_factory


@contextmanager
def get_session() -> Iterator[Session]:
    """Provide a transactional session scope around a series of operations."""
    session = _get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
