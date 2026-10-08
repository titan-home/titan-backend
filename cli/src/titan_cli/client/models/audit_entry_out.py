from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from titan_cli.client.models.action_class import ActionClass
from titan_cli.client.models.domain import Domain
from titan_cli.client.models.entry_status import EntryStatus
from titan_cli.client.models.mode import Mode

T = TypeVar("T", bound="AuditEntryOut")


@_attrs_define
class AuditEntryOut:
    """One call in the user's audit log, or an undo (decisions #108, #131).

    Attributes:
        id (UUID):
        tool (str):
        summary (str):
        domain (Domain): The area of the user's data a tool works in (decision #114).

            A user's mode for a class can differ per domain (decision #10). A value is
            added with the first tool of its domain.
        action_class (ActionClass): How much a call can change, which sets its default mode (decision #38).

            A user can change the mode of one class in one domain (decision #10).
        mode (Mode | None): The mode the policy ran the call in; null for an undo.
        status (EntryStatus): Where a call stands in its life (decision #111).
        undoable (bool): Whether the call's tool could be undone when it was called.
        undoes_entry_id (None | UUID): For an undo, the entry it took back; null otherwise.
        created_at (datetime.datetime):
    """

    id: UUID
    tool: str
    summary: str
    domain: Domain
    action_class: ActionClass
    mode: Mode | None
    status: EntryStatus
    undoable: bool
    undoes_entry_id: None | UUID
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        tool = self.tool

        summary = self.summary

        domain = self.domain.value

        action_class = self.action_class.value

        mode: None | str
        if isinstance(self.mode, Mode):
            mode = self.mode.value
        else:
            mode = self.mode

        status = self.status.value

        undoable = self.undoable

        undoes_entry_id: None | str
        if isinstance(self.undoes_entry_id, UUID):
            undoes_entry_id = str(self.undoes_entry_id)
        else:
            undoes_entry_id = self.undoes_entry_id

        created_at = self.created_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "tool": tool,
                "summary": summary,
                "domain": domain,
                "action_class": action_class,
                "mode": mode,
                "status": status,
                "undoable": undoable,
                "undoes_entry_id": undoes_entry_id,
                "created_at": created_at,
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

        def _parse_mode(data: object) -> Mode | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                mode_type_0 = Mode(data)

                return mode_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(Mode | None, data)

        mode = _parse_mode(d.pop("mode"))

        status = EntryStatus(d.pop("status"))

        undoable = d.pop("undoable")

        def _parse_undoes_entry_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                undoes_entry_id_type_0 = UUID(data)

                return undoes_entry_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        undoes_entry_id = _parse_undoes_entry_id(d.pop("undoes_entry_id"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        audit_entry_out = cls(
            id=id,
            tool=tool,
            summary=summary,
            domain=domain,
            action_class=action_class,
            mode=mode,
            status=status,
            undoable=undoable,
            undoes_entry_id=undoes_entry_id,
            created_at=created_at,
        )

        audit_entry_out.additional_properties = d
        return audit_entry_out

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
