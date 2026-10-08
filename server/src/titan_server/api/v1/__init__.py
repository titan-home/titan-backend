"""Version 1 of the HTTP API, served under /api/v1.

Each module of this package has its own `router` without a prefix; add it
here and it is served under /api/v1.
"""

from fastapi import APIRouter

from titan_server.api.v1 import approvals, audit, chat, devices, me, policy

router = APIRouter(prefix="/api/v1")
router.include_router(approvals.router)
router.include_router(audit.router)
router.include_router(chat.router)
router.include_router(devices.router)
router.include_router(me.router)
router.include_router(policy.router)
