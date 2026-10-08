from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from titan_cli.client import errors
from titan_cli.client.client import AuthenticatedClient, Client
from titan_cli.client.models.audit_entry_out import AuditEntryOut
from titan_cli.client.models.problem import Problem
from titan_cli.client.types import Response


def _get_kwargs(
    entry_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/audit/entries/{entry_id}/undo".format(
            entry_id=quote(str(entry_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AuditEntryOut | Problem | None:
    if response.status_code == 200:
        response_200 = AuditEntryOut.from_dict(response.json())

        return response_200

    if response.status_code == 401:
        response_401 = Problem.from_dict(response.json())

        return response_401

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = Problem.from_dict(response.json())

        return response_409

    if response.status_code == 422:
        response_422 = Problem.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[AuditEntryOut | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    entry_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[AuditEntryOut | Problem]:
    """Undo Entry

     Undo an action from its entry, whole; answer with the undo's own entry.

    Every refusal is 409 with a plain detail: never ran, cannot be undone,
    already undone, older than one year, or changed later.

    Args:
        entry_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AuditEntryOut | Problem]
    """

    kwargs = _get_kwargs(
        entry_id=entry_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    entry_id: UUID,
    *,
    client: AuthenticatedClient,
) -> AuditEntryOut | Problem | None:
    """Undo Entry

     Undo an action from its entry, whole; answer with the undo's own entry.

    Every refusal is 409 with a plain detail: never ran, cannot be undone,
    already undone, older than one year, or changed later.

    Args:
        entry_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AuditEntryOut | Problem
    """

    return sync_detailed(
        entry_id=entry_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    entry_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[AuditEntryOut | Problem]:
    """Undo Entry

     Undo an action from its entry, whole; answer with the undo's own entry.

    Every refusal is 409 with a plain detail: never ran, cannot be undone,
    already undone, older than one year, or changed later.

    Args:
        entry_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AuditEntryOut | Problem]
    """

    kwargs = _get_kwargs(
        entry_id=entry_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    entry_id: UUID,
    *,
    client: AuthenticatedClient,
) -> AuditEntryOut | Problem | None:
    """Undo Entry

     Undo an action from its entry, whole; answer with the undo's own entry.

    Every refusal is 409 with a plain detail: never ran, cannot be undone,
    already undone, older than one year, or changed later.

    Args:
        entry_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AuditEntryOut | Problem
    """

    return (
        await asyncio_detailed(
            entry_id=entry_id,
            client=client,
        )
    ).parsed
