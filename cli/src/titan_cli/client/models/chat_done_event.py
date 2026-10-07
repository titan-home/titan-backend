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

T = TypeVar("T", bound="ChatDoneEvent")


@_attrs_define
class ChatDoneEvent:
    """The reply is complete and stored; the stream ends.

    Attributes:
        type_ (Literal['done']):  Default: 'done'.
        message_id (UUID):
    """

    message_id: UUID
    type_: Literal["done"] = "done"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        message_id = str(self.message_id)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "message_id": message_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        type_ = cast(Literal["done"], d.pop("type"))
        if type_ != "done":
            raise ValueError(f"type must match const 'done', got '{type_}'")

        message_id = UUID(d.pop("message_id"))

        chat_done_event = cls(
            type_=type_,
            message_id=message_id,
        )

        chat_done_event.additional_properties = d
        return chat_done_event

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
