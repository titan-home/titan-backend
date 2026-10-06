from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from titan_cli.client.models.whoami_device_out import WhoamiDeviceOut


T = TypeVar("T", bound="WhoamiOut")


@_attrs_define
class WhoamiOut:
    """Who is signed in and on which device (accounts.md, sign in, criterion 5).

    Attributes:
        username (str):
        device (WhoamiDeviceOut): The device the request came from.
    """

    username: str
    device: WhoamiDeviceOut
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        username = self.username

        device = self.device.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "username": username,
                "device": device,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from titan_cli.client.models.whoami_device_out import (
            WhoamiDeviceOut,
        )

        d = dict(src_dict)
        username = d.pop("username")

        device = WhoamiDeviceOut.from_dict(d.pop("device"))

        whoami_out = cls(
            username=username,
            device=device,
        )

        whoami_out.additional_properties = d
        return whoami_out

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
