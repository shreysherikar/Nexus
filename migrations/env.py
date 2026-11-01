from __future__ import annotations

import os
from pathlib import Path
import sys
from logging.config import fileConfig

# Ensure src/ directory is in sys.path so nexus package is discoverable
src_path = str(Path(__file__).resolve().parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from sqlalchemy import engine_from_config, pool

from alembic import context

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if context.config.config_file_name is not None:
    try:
        fileConfig(context.config.config_file_name)
    except Exception:
        pass

# Add application models metadata
from nexus.incidents.repository import Base

target_metadata = Base.metadata


def get_url() -> str:
    """Resolve database URL.

    Precedence rules:
    1. CLI -x argument override: alembic -x url=<url>
    2. If invoked from CLI (cmd_opts is present), prefer DATABASE_URL or
       NEXUS_DATABASE_URL environment variable over alembic.ini defaults.
    3. If invoked programmatically (cmd_opts is None, e.g. tests or scripts),
       respect the URL supplied through the Alembic Config object
       (e.g. alembic_cfg.set_main_option("sqlalchemy.url", test_url)).
    4. Fall back to environment variable, Config option, or PostgreSQL default.
    """
    # 1. CLI -x argument override
    x_args = {}
    if hasattr(context, "get_x_argument"):
        try:
            x_args = context.get_x_argument(as_dictionary=True)
        except Exception:
            x_args = {}
    if x_args.get("url"):
        return x_args["url"]

    config_url = context.config.get_main_option("sqlalchemy.url")
    env_url = os.getenv("DATABASE_URL") or os.getenv("NEXUS_DATABASE_URL")
    default_pg_url = "postgresql+psycopg://nexus:nexus@localhost:5432/nexus_db"

    def _normalize_driver(raw_url: str) -> str:
        if raw_url.startswith("postgresql://"):
            return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return raw_url

    # 2. CLI execution: prefer DATABASE_URL from environment
    is_cli = getattr(context.config, "cmd_opts", None) is not None
    if is_cli:
        if env_url and env_url.strip():
            return _normalize_driver(env_url.strip())
        if config_url and config_url.strip():
            return _normalize_driver(config_url.strip())
        return default_pg_url

    # 3. Programmatic execution: respect supplied Config option
    if config_url and config_url.strip():
        # If config_url is the generic default and DATABASE_URL is set, use DATABASE_URL;
        # if config_url was explicitly set or differs from default, respect config_url.
        if config_url.strip() == default_pg_url and env_url and env_url.strip():
            return _normalize_driver(env_url.strip())
        return _normalize_driver(config_url.strip())

    # 4. Fallback to env_url or default
    if env_url and env_url.strip():
        return _normalize_driver(env_url.strip())
    return default_pg_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = context.config.get_section(context.config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
