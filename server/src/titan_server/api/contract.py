"""The API contract, written the way shared/contracts/openapi.json holds it.

Export it into titan-shared (decision #87):
uv run python -m titan_server.api.contract > ../titan-shared/contracts/openapi.json
"""

import json

from titan_server.api.app import create_app


def contract() -> str:
    """The OpenAPI schema the API serves, as stable text."""
    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    print(contract(), end="")
