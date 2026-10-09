"""Cursors for paging the audit log by time and id (decision #124)."""

import base64
import uuid
from datetime import datetime

from titan_core.domains.audit.models import AuditEntry


def cursor(entry: AuditEntry) -> str:
    """The opaque cursor after entry: its time and id (decision #124)."""
    raw = f"{entry.created_at.isoformat()}|{entry.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def parse_cursor(text: str) -> tuple[datetime, uuid.UUID]:
    """The time and id a cursor holds; raises ValueError for anything else."""
    # Every failure here, from bad base64 to a bad UUID, is a ValueError.
    created_at, entry_id = base64.urlsafe_b64decode(text.encode()).decode().split("|")
    return datetime.fromisoformat(created_at), uuid.UUID(entry_id)
