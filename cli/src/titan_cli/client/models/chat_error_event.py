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

T = TypeVar("T", bound="ChatErrorEvent")


@_attrs_define
class ChatErrorEvent:
    """The turn failed and nothing of it was kept; the stream ends.

    Attributes:
        type_ (Literal['error']):  Default: 'error'.
        title (str):
    """

    title: str
    type_: Literal["error"] = "error"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "title": title,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        type_ = cast(Literal["error"], d.pop("type"))
        if type_ != "error":
            raise ValueError(f"type must match const 'error', got '{type_}'")

        title = d.pop("title")

        chat_error_event = cls(
            type_=type_,
            title=title,
        )

        chat_error_event.additional_properties = d
        return chat_error_event

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
