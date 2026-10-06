"""The devices table: one row per CLI, phone or browser session."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from titan_server.db import Base

if TYPE_CHECKING:
    from titan_server.domains.accounts.models.user import User

MAX_DEVICE_NAME_LENGTH = 255


class Device(Base):
    """A paired CLI, phone or browser session; revoked_at cuts it off."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    user: Mapped["User"] = relationship()
    name: Mapped[str] = mapped_column(String(MAX_DEVICE_NAME_LENGTH))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
