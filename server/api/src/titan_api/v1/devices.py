"""Devices: signing in from a CLI, a phone or a browser pairs a device."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from titan_api.dependencies import BearerToken, Session
from titan_api.guessing import GuessingLimit
from titan_api.problems import problems
from titan_core.domains.accounts.devices import InvalidCredentialsError, sign_in
from titan_core.domains.accounts.models.device import MAX_DEVICE_NAME_LENGTH
from titan_core.domains.accounts.models.user import MAX_USERNAME_LENGTH
from titan_core.domains.accounts.passwords import MAX_PASSWORD_LENGTH


class DeviceRegistrationIn(BaseModel):
    """A sign-in: the account's credentials and a name for this device."""

    username: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH)
    password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    name: str = Field(min_length=1, max_length=MAX_DEVICE_NAME_LENGTH)


class DeviceRegistrationOut(BaseModel):
    """The paired device and its token, shown to the device this one time."""

    id: uuid.UUID
    name: str
    token: str


router = APIRouter()

responses = problems(401, 429)
responses[429]["headers"] = {
    "Retry-After": {
        "description": (
            "Whole seconds, at least 1, until this address may try this username again."
        ),
        "schema": {"type": "integer"},
    }
}


# The bearer token is optional here: FastAPI lists it as required, and the
# empty requirement it gets added to its list says "or none at all".
@router.post(
    "/devices",
    status_code=201,
    responses=responses,
    openapi_extra={"security": [{}]},
)
async def add_device(
    device_registration: DeviceRegistrationIn,
    session: Session,
    old_token: BearerToken,
    request: Request,
) -> DeviceRegistrationOut:
    """Sign in with a username and password and get a token for this device.

    A device that still holds its token sends it as a bearer token; then its
    token is replaced instead of pairing a new device (decision #24).
    """
    # After 10 failures within 15 minutes from one address for one username,
    # that pair is refused (decision #27), before the password is checked, so
    # a right one gets the same answer.
    limit: GuessingLimit = request.app.state.guessing_limit
    address = request.client.host if request.client else ""
    username = device_registration.username
    retry_after = limit.attempt(address, username)
    if retry_after is not None:
        raise HTTPException(429, headers={"Retry-After": str(retry_after)})
    try:
        device, token = await sign_in(
            session,
            device_registration.username,
            device_registration.password.get_secret_value(),
            device_registration.name,
            old_token,
        )
    except InvalidCredentialsError:
        raise HTTPException(401) from None
    limit.succeeded(address, username)
    return DeviceRegistrationOut(id=device.id, name=device.name, token=token)
