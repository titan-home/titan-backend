from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from titan_cli.client.models.audit_entry_out import AuditEntryOut


T = TypeVar("T", bound="AuditEntryPage")


@_attrs_define
class AuditEntryPage:
    """A page of the user's audit log, newest first (decision #124).

    Attributes:
        items (list[AuditEntryOut]):
        next_ (None | str): Send it back as `after` for the next page; null on the last.
    """

    items: list[AuditEntryOut]
    next_: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        next_: None | str
        next_ = self.next_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "items": items,
                "next": next_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from titan_cli.client.models.audit_entry_out import (
            AuditEntryOut,
        )

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = AuditEntryOut.from_dict(items_item_data)

            items.append(items_item)

        def _parse_next_(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        next_ = _parse_next_(d.pop("next"))

        audit_entry_page = cls(
            items=items,
            next_=next_,
        )

        audit_entry_page.additional_properties = d
        return audit_entry_page

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
