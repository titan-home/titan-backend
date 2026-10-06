"""Tables of the accounts domain: users and their devices."""

from titan_server.domains.accounts.models.device import Device
from titan_server.domains.accounts.models.user import User

__all__ = ["Device", "User"]
