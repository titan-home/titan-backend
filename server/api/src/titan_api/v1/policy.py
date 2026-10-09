"""Policy: each user's own mode for an action class in a domain (decision #117)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from titan_api.dependencies import CurrentDevice, Session
from titan_api.problems import problems
from titan_core.domains.audit.models import ActionClass, Domain, Mode
from titan_core.domains.policy import service as policy


class PolicyModeOut(BaseModel):
    """The mode one action class runs in, in one domain, for the signed-in user."""

    domain: Domain
    action_class: ActionClass
    mode: Mode
    own: bool = Field(description="The user's own mode rather than the default.")


class PolicyModeIn(BaseModel):
    """The mode the user wants for one action class in one domain."""

    mode: Mode


router = APIRouter(prefix="/policy")


# NOTE: not paged, unlike other lists (development rules, 9): it is every
# domain times four classes, a few dozen rows at most.
@router.get("/modes", responses=problems(401))
async def list_modes(device: CurrentDevice, session: Session) -> list[PolicyModeOut]:
    """The mode every action class runs in, in every domain, and whose it is."""
    return [
        PolicyModeOut(
            domain=mode.domain,
            action_class=mode.action_class,
            mode=mode.mode,
            own=mode.own,
        )
        for mode in await policy.modes_in_effect(session, device.user_id)
    ]


@router.put("/modes/{domain}/{action_class}", responses=problems(401, 422))
async def set_mode(
    domain: Domain,
    action_class: ActionClass,
    policy_mode: PolicyModeIn,
    device: CurrentDevice,
    session: Session,
) -> PolicyModeOut:
    """Set the user's own mode for one action class in one domain.

    external and destructive can only be confirm or deny (decision #116).
    """
    try:
        await policy.set_override(
            session, device.user_id, domain, action_class, policy_mode.mode
        )
    except policy.ModeBelowFloorError:
        raise HTTPException(
            422, f"{action_class} can only be confirm or deny."
        ) from None
    return PolicyModeOut(
        domain=domain, action_class=action_class, mode=policy_mode.mode, own=True
    )


@router.delete(
    "/modes/{domain}/{action_class}", status_code=204, responses=problems(401, 422)
)
async def reset_mode(
    domain: Domain, action_class: ActionClass, device: CurrentDevice, session: Session
) -> None:
    """Return one action class in one domain to its default mode."""
    await policy.reset_override(session, device.user_id, domain, action_class)
