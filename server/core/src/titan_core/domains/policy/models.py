"""The policy_overrides table (decisions #10, #114, #116)."""

import uuid

from sqlalchemy import CheckConstraint, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from titan_core.db import Base
from titan_core.domains.audit.models import ActionClass, Domain, Mode


class PolicyOverride(Base):
    """A user's own mode for one action class in one domain."""

    __tablename__ = "policy_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "domain", "action_class"),
        # What cannot be taken back always passes a person (decision #116).
        CheckConstraint(
            "action_class NOT IN ('external', 'destructive')"
            " OR mode IN ('confirm', 'deny')",
            name="policy_overrides_floor",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    domain: Mapped[Domain] = mapped_column(
        Enum(
            Domain,
            name="domain",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda domains: [domain.value for domain in domains],
        )
    )
    action_class: Mapped[ActionClass] = mapped_column(
        Enum(
            ActionClass,
            name="action_class",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda classes: [value.value for value in classes],
        )
    )
    mode: Mapped[Mode] = mapped_column(
        Enum(
            Mode,
            name="mode",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda modes: [mode.value for mode in modes],
        )
    )
