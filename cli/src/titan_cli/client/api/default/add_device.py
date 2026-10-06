from http import HTTPStatus
from typing import Any

import httpx

from titan_cli.client import errors
from titan_cli.client.client import AuthenticatedClient, Client
from titan_cli.client.models.device_registration_in import DeviceRegistrationIn
from titan_cli.client.models.device_registration_out import DeviceRegistrationOut
from titan_cli.client.models.problem import Problem
from titan_cli.client.types import Response


def _get_kwargs(
    *,
    body: DeviceRegistrationIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/devices",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DeviceRegistrationOut | Problem | None:
    if response.status_code == 201:
        response_201 = DeviceRegistrationOut.from_dict(response.json())

        return response_201

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
) -> Response[DeviceRegistrationOut | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: DeviceRegistrationIn,
) -> Response[DeviceRegistrationOut | Problem]:
    """Add Device

     Sign in with a username and password and get a token for this device.

    A device that still holds its token sends it as a bearer token; then its
    token is replaced instead of pairing a new device (decision #24).

    Args:
        body (DeviceRegistrationIn): A sign-in: the account's credentials and a name for this
            device.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeviceRegistrationOut | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: DeviceRegistrationIn,
) -> DeviceRegistrationOut | Problem | None:
    """Add Device

     Sign in with a username and password and get a token for this device.

    A device that still holds its token sends it as a bearer token; then its
    token is replaced instead of pairing a new device (decision #24).

    Args:
        body (DeviceRegistrationIn): A sign-in: the account's credentials and a name for this
            device.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeviceRegistrationOut | Problem
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: DeviceRegistrationIn,
) -> Response[DeviceRegistrationOut | Problem]:
    """Add Device

     Sign in with a username and password and get a token for this device.

    A device that still holds its token sends it as a bearer token; then its
    token is replaced instead of pairing a new device (decision #24).

    Args:
        body (DeviceRegistrationIn): A sign-in: the account's credentials and a name for this
            device.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeviceRegistrationOut | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: DeviceRegistrationIn,
) -> DeviceRegistrationOut | Problem | None:
    """Add Device

     Sign in with a username and password and get a token for this device.

    A device that still holds its token sends it as a bearer token; then its
    token is replaced instead of pairing a new device (decision #24).

    Args:
        body (DeviceRegistrationIn): A sign-in: the account's credentials and a name for this
            device.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeviceRegistrationOut | Problem
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
