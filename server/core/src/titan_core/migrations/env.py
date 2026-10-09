"""How Alembic connects to the database and finds the tables to compare."""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from titan_core.db import Base, database_url
from titan_core.domains.accounts import models  # noqa: F401  registers the tables
from titan_core.domains.audit import models as audit_models  # noqa: F401
from titan_core.domains.chat import models as chat_models  # noqa: F401
from titan_core.domains.policy import models as policy_models  # noqa: F401
from titan_core.domains.tasks import models as task_models  # noqa: F401

config = context.config
# titan-admin and the tests pass the URL; the alembic command reads the environment.
url = config.attributes.get("url") or database_url()


def migrate(connection: Connection) -> None:
    """Run the pending migrations on one connection, in one transaction."""
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run() -> None:
    """Connect, migrate and disconnect."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


asyncio.run(run())
