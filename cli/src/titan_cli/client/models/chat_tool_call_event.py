from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="ChatToolCallEvent")


@_attrs_define
class ChatToolCallEvent:
    """A tool call that ran: its name, a line a person can read, its outcome.

    Attributes:
        type_ (Literal['tool_call']):  Default: 'tool_call'.
        name (str):
        summary (str):
        ok (bool):
    """

    name: str
    summary: str
    ok: bool
    type_: Literal["tool_call"] = "tool_call"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        name = self.name

        summary = self.summary

        ok = self.ok

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "name": name,
                "summary": summary,
                "ok": ok,
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

        chat_tool_call_event = cls(
            type_=type_,
            name=name,
            summary=summary,
            ok=ok,
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
