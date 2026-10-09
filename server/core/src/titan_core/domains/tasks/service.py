"""Creating tasks; every function acts for one user."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from titan_core.domains.tasks.models import Task


async def create_task(session: AsyncSession, user_id: uuid.UUID, title: str) -> Task:
    """Add an open task for the user and return it."""
    task = Task(user_id=user_id, title=title)
    session.add(task)
    await session.flush()
    return task
