from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from titan_cli.client.models.action_class import ActionClass
from titan_cli.client.models.chat_tool_call_event_status import ChatToolCallEventStatus
from titan_cli.client.models.domain import Domain

T = TypeVar("T", bound="ChatToolCallEvent")


@_attrs_define
class ChatToolCallEvent:
    """A tool call, run or not: its name, a line a person can read, its status.

    The status is the one when the reply was made; a `pending` call waits for
    the user's approval, and its entry says what became of it later.

        Attributes:
            type_ (Literal['tool_call']):  Default: 'tool_call'.
            name (str):
            summary (str):
            ok (bool):
            status (ChatToolCallEventStatus):
            entry_id (UUID):
            domain (Domain): The area of the user's data a tool works in (decision #114).

                A user's mode for a class can differ per domain (decision #10). A value is
                added with the first tool of its domain.
            action_class (ActionClass): How much a call can change, which sets its default mode (decision #38).

                A user can change the mode of one class in one domain (decision #10).
    """

    name: str
    summary: str
    ok: bool
    status: ChatToolCallEventStatus
    entry_id: UUID
    domain: Domain
    action_class: ActionClass
    type_: Literal["tool_call"] = "tool_call"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        name = self.name

        summary = self.summary

        ok = self.ok

        status = self.status.value

        entry_id = str(self.entry_id)

        domain = self.domain.value

        action_class = self.action_class.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "name": name,
                "summary": summary,
                "ok": ok,
                "status": status,
                "entry_id": entry_id,
                "domain": domain,
                "action_class": action_class,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        type_ = cast(Literal["tool_call"], d.pop("type"))
        if type_ != "tool_call":
            raise ValueError(f"type must match const 'tool_call', got '{type_}'")

        name = d.pop("name")

        summary = d.pop("summary")

        ok = d.pop("ok")

        status = ChatToolCallEventStatus(d.pop("status"))

        entry_id = UUID(d.pop("entry_id"))

        domain = Domain(d.pop("domain"))

        action_class = ActionClass(d.pop("action_class"))

        chat_tool_call_event = cls(
            type_=type_,
            name=name,
            summary=summary,
            ok=ok,
            status=status,
            entry_id=entry_id,
            domain=domain,
            action_class=action_class,
        )

        chat_tool_call_event.additional_properties = d
        return chat_tool_call_event

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
