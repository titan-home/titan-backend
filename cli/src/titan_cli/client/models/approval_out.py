from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from titan_cli.client.models.action_class import ActionClass
from titan_cli.client.models.domain import Domain
from titan_cli.client.models.entry_status import EntryStatus

T = TypeVar("T", bound="ApprovalOut")


@_attrs_define
class ApprovalOut:
    """A call that waits, or waited, for the user's approval.

    Attributes:
        id (UUID): The call's audit entry.
        tool (str):
        summary (str):
        domain (Domain): The area of the user's data a tool works in (decision #114).

            A user's mode for a class can differ per domain (decision #10). A value is
            added with the first tool of its domain.
        action_class (ActionClass): How much a call can change, which sets its default mode (decision #38).

            A user can change the mode of one class in one domain (decision #10).
        status (EntryStatus): Where a call stands in its life (decision #111).
        created_at (datetime.datetime):
        expires_at (datetime.datetime): When a pending request expires: its creation time plus the node's setting in
            effect now (decision #127).
    """

    id: UUID
    tool: str
    summary: str
    domain: Domain
    action_class: ActionClass
    status: EntryStatus
    created_at: datetime.datetime
    expires_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        tool = self.tool

        summary = self.summary

        domain = self.domain.value

        action_class = self.action_class.value

        status = self.status.value

        created_at = self.created_at.isoformat()

        expires_at = self.expires_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "tool": tool,
                "summary": summary,
                "domain": domain,
                "action_class": action_class,
                "status": status,
                "created_at": created_at,
                "expires_at": expires_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        tool = d.pop("tool")

        summary = d.pop("summary")

        domain = Domain(d.pop("domain"))

        action_class = ActionClass(d.pop("action_class"))

        status = EntryStatus(d.pop("status"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        expires_at = datetime.datetime.fromisoformat(d.pop("expires_at"))

        approval_out = cls(
            id=id,
            tool=tool,
            summary=summary,
            domain=domain,
            action_class=action_class,
            status=status,
            created_at=created_at,
            expires_at=expires_at,
        )

        approval_out.additional_properties = d
        return approval_out

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
