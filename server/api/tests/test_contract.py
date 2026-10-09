"""Tests that the API serves exactly the contract in shared/contracts/."""

import json
from pathlib import Path

from titan_api.contract import contract

SHARED_CONTRACT = Path(__file__).parents[3] / "shared/contracts/openapi.json"


def test_the_api_serves_the_shared_contract() -> None:
    assert contract() == SHARED_CONTRACT.read_text(encoding="utf-8"), (
        "The API differs from shared/contracts/openapi.json; export it with "
        "python -m titan_api.contract into titan-shared (decision #87)."
    )


def test_every_error_is_a_problem() -> None:
    schema = json.loads(contract())
    errors = [
        response
        for operations in schema["paths"].values()
        for operation in operations.values()
        for status, response in operation["responses"].items()
        if not status.startswith("2")
    ]
    assert errors
    for response in errors:
        assert response["content"] == {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/Problem"}
            }
        }
    assert "HTTPValidationError" not in schema["components"]["schemas"]
