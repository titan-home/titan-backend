"""Dependencies shared by the API routes."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from titan_server.domains.accounts.authentication import authenticate
from titan_server.domains.accounts.models import Device


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Give a route one transaction: committed if it returns, rolled back if not."""
    async with AsyncSession(request.app.state.engine) as session, session.begin():
        yield session


# scope="function": the commit happens before the response is sent, so a
# failed commit answers with an error instead of a success that did not stick.
Session = Annotated[AsyncSession, Depends(get_session, scope="function")]
"""Declare `session: Session` in a route to get the request's database session."""


def background_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    """Open sessions for work that outlives the request, such as a chat turn."""
    return async_sessionmaker(request.app.state.engine)


BackgroundSessions = Annotated[
    async_sessionmaker[AsyncSession], Depends(background_sessions)
]
"""Declare `sessions: BackgroundSessions` to open sessions of your own."""


bearer = HTTPBearer(auto_error=False, description="The device token, titan_v1_…")


def bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str | None:
    """Return the token from `Authorization: Bearer <token>`, or None."""
    return credentials.credentials if credentials else None


BearerToken = Annotated[str | None, Depends(bearer_token)]
"""Declare `token: BearerToken` to get the request's token, or None."""


async def current_device(session: Session, token: BearerToken) -> Device:
    """Return the device the request's token belongs to, or answer 401."""
    device = await authenticate(session, token) if token else None
    if device is None:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    return device


CurrentDevice = Annotated[Device, Depends(current_device)]
"""Declare `device: CurrentDevice` in a route that needs a signed-in device."""
