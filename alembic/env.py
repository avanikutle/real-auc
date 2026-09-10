"""Alembic migration environment — wired to SQLAlchemy models."""
from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ---------------------------------------------------------------------------
# Import our models so Alembic can see metadata for autogenerate
# ---------------------------------------------------------------------------
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from auction_pipeline.db.models import Base  # noqa: E402
from auction_pipeline import load_config  # noqa: E402

# Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Override URL from config.yaml so a single source of truth exists."""
    cfg = load_config()
    db_url = cfg["database"]["url"]
    # Resolve relative sqlite paths to repo root
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////"):
        rel = db_url[len("sqlite:///"):]
        import pathlib
        abs_path = pathlib.Path(__file__).parent.parent / rel
        return f"sqlite:///{abs_path}"
    return db_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection needed)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with active DB connection)."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER TABLE support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
