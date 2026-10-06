"""Devices: signing in from a CLI, a phone or a browser pairs a device."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr

from titan_server.api.dependencies import BearerToken, Session
from titan_server.api.problems import problems
from titan_server.domains.accounts.devices import InvalidCredentialsError, sign_in
from titan_server.domains.accounts.models.device import MAX_DEVICE_NAME_LENGTH
from titan_server.domains.accounts.models.user import MAX_USERNAME_LENGTH
from titan_server.domains.accounts.passwords import MAX_PASSWORD_LENGTH


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


# The bearer token is optional here: FastAPI lists it as required, and the
# empty requirement it gets added to its list says "or none at all".
@router.post(
    "/devices",
    status_code=201,
    responses=problems(401),
    openapi_extra={"security": [{}]},
)
async def add_device(
    device_registration: DeviceRegistrationIn, session: Session, old_token: BearerToken
) -> DeviceRegistrationOut:
    """Sign in with a username and password and get a token for this device.

    A device that still holds its token sends it as a bearer token; then its
    token is replaced instead of pairing a new device (decision #24).
    """

    try:
        device, token = await sign_in(
            session,
            device_registration.username,
            device_registration.password.get_secret_value(),
            device_registration.name,
            old_token,
        )
        return DeviceRegistrationOut(id=device.id, name=device.name, token=token)
    except InvalidCredentialsError:
        raise HTTPException(401) from None
