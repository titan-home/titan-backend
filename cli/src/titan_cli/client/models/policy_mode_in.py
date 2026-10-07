from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from titan_cli.client.models.mode import Mode

T = TypeVar("T", bound="PolicyModeIn")


@_attrs_define
class PolicyModeIn:
    """The mode the user wants for one action class in one domain.

    Attributes:
        mode (Mode): What happens when the agent calls a tool (autonomy spec, modes).
    """

    mode: Mode
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        mode = self.mode.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "mode": mode,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        mode = Mode(d.pop("mode"))

        policy_mode_in = cls(
            mode=mode,
        )

        policy_mode_in.additional_properties = d
        return policy_mode_in

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
