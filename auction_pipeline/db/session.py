"""Database session factory for auction_pipeline."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session, sessionmaker

from auction_pipeline import load_config

_SessionFactory: sessionmaker | None = None


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    cfg = load_config()
    db_url = cfg["database"]["url"]
    # Resolve relative sqlite paths to repo root
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////"):
        rel = db_url[len("sqlite:///"):]
        abs_path = Path(__file__).parent.parent.parent / rel
        db_url = f"sqlite:///{abs_path}"
    return create_engine(db_url, echo=False, future=True)


def get_session() -> Session:
    """Return a new SQLAlchemy session. Caller is responsible for closing it."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionFactory()


def init_db() -> None:
    """Create all tables (used in tests / Alembic bypass mode)."""
    from auction_pipeline.db.models import Base
    Base.metadata.create_all(get_engine())
