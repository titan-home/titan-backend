from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from titan_cli.client.models.action_class import ActionClass
from titan_cli.client.models.domain import Domain
from titan_cli.client.models.mode import Mode

T = TypeVar("T", bound="PolicyModeOut")


@_attrs_define
class PolicyModeOut:
    """The mode one action class runs in, in one domain, for the signed-in user.

    Attributes:
        domain (Domain): The area of the user's data a tool works in (decision #114).

            A user's mode for a class can differ per domain (decision #10). A value is
            added with the first tool of its domain.
        action_class (ActionClass): How much a call can change, which sets its default mode (decision #38).

            A user can change the mode of one class in one domain (decision #10).
        mode (Mode): What happens when the agent calls a tool (autonomy spec, modes).
        own (bool): The user's own mode rather than the default.
    """

    domain: Domain
    action_class: ActionClass
    mode: Mode
    own: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        domain = self.domain.value

        action_class = self.action_class.value

        mode = self.mode.value

        own = self.own

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "domain": domain,
                "action_class": action_class,
                "mode": mode,
                "own": own,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        domain = Domain(d.pop("domain"))

        action_class = ActionClass(d.pop("action_class"))

        mode = Mode(d.pop("mode"))

        own = d.pop("own")

        policy_mode_out = cls(
            domain=domain,
            action_class=action_class,
            mode=mode,
            own=own,
        )

        policy_mode_out.additional_properties = d
        return policy_mode_out

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
