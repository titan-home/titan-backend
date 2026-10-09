"""The signed-in user and device: who is on the other end of a token."""

from fastapi import APIRouter
from pydantic import BaseModel

from titan_api.dependencies import CurrentDevice
from titan_api.problems import problems


class WhoamiDeviceOut(BaseModel):
    """The device the request came from."""

    name: str


class WhoamiOut(BaseModel):
    """Who is signed in and on which device (accounts.md, sign in, criterion 5)."""

    username: str
    device: WhoamiDeviceOut


router = APIRouter()


@router.get("/me", responses=problems(401))
async def whoami(device: CurrentDevice) -> WhoamiOut:
    """Tell who is signed in on the device that sent this request."""
    return WhoamiOut(
        username=device.user.username,
        device=WhoamiDeviceOut(name=device.name),
    )
