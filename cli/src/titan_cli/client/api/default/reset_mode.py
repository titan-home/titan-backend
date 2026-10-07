from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from titan_cli.client import errors
from titan_cli.client.client import AuthenticatedClient, Client
from titan_cli.client.models.action_class import ActionClass
from titan_cli.client.models.domain import Domain
from titan_cli.client.models.problem import Problem
from titan_cli.client.types import Response


def _get_kwargs(
    domain: Domain,
    action_class: ActionClass,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/api/v1/policy/modes/{domain}/{action_class}".format(
            domain=quote(str(domain), safe=""),
            action_class=quote(str(action_class), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | Problem | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

    if response.status_code == 401:
        response_401 = Problem.from_dict(response.json())

        return response_401

    if response.status_code == 422:
        response_422 = Problem.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    domain: Domain,
    action_class: ActionClass,
    *,
    client: AuthenticatedClient,
) -> Response[Any | Problem]:
    """Reset Mode

     Return one action class in one domain to its default mode.

    Args:
        domain (Domain): The area of the user's data a tool works in (decision #114).

            A user's mode for a class can differ per domain (decision #10). A value is
            added with the first tool of its domain.
        action_class (ActionClass): How much a call can change, which sets its default mode
            (decision #38).

            A user can change the mode of one class in one domain (decision #10).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem]
    """

    kwargs = _get_kwargs(
        domain=domain,
        action_class=action_class,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    domain: Domain,
    action_class: ActionClass,
    *,
    client: AuthenticatedClient,
) -> Any | Problem | None:
    """Reset Mode

     Return one action class in one domain to its default mode.

    Args:
        domain (Domain): The area of the user's data a tool works in (decision #114).

            A user's mode for a class can differ per domain (decision #10). A value is
            added with the first tool of its domain.
        action_class (ActionClass): How much a call can change, which sets its default mode
            (decision #38).

            A user can change the mode of one class in one domain (decision #10).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem
    """

    return sync_detailed(
        domain=domain,
        action_class=action_class,
        client=client,
    ).parsed


async def asyncio_detailed(
    domain: Domain,
    action_class: ActionClass,
    *,
    client: AuthenticatedClient,
) -> Response[Any | Problem]:
    """Reset Mode

     Return one action class in one domain to its default mode.

    Args:
        domain (Domain): The area of the user's data a tool works in (decision #114).

            A user's mode for a class can differ per domain (decision #10). A value is
            added with the first tool of its domain.
        action_class (ActionClass): How much a call can change, which sets its default mode
            (decision #38).

            A user can change the mode of one class in one domain (decision #10).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem]
    """

    kwargs = _get_kwargs(
        domain=domain,
        action_class=action_class,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    domain: Domain,
    action_class: ActionClass,
    *,
    client: AuthenticatedClient,
) -> Any | Problem | None:
    """Reset Mode

     Return one action class in one domain to its default mode.

    Args:
        domain (Domain): The area of the user's data a tool works in (decision #114).

            A user's mode for a class can differ per domain (decision #10). A value is
            added with the first tool of its domain.
        action_class (ActionClass): How much a call can change, which sets its default mode
            (decision #38).

            A user can change the mode of one class in one domain (decision #10).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem
    """

    return (
        await asyncio_detailed(
            domain=domain,
            action_class=action_class,
            client=client,
        )
    ).parsed
