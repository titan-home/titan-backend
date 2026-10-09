"""The FastAPI application of the TITAN API."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from titan_api import v1
from titan_api.problems import add_problem_handlers, with_problems
from titan_core.db import create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Connect to the database when the API starts, disconnect when it stops."""
    app.state.engine = create_engine()
    yield
    await app.state.engine.dispose()


def create_app() -> FastAPI:
    """Build the API application with every route mounted."""
    # The contract is generated from this app (decision #87), so nothing that
    # is not part of /api/v1 may show up in the schema; the interactive docs
    # stay off on a node.
    app = FastAPI(
        title="TITAN API",
        version="1",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        # Client code is generated from the contract, so operation ids become
        # method names there: whoami, not whoami_api_v1_me_get.
        generate_unique_id_function=lambda route: route.name,
    )

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        """Tell the controller the API is up."""
        return {"status": "ok"}

    add_problem_handlers(app)
    app.include_router(v1.router)

    fastapi_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        """The contract: FastAPI's schema with every error as problem+json."""
        return with_problems(fastapi_openapi())

    app.openapi = openapi  # type: ignore[method-assign]
    return app
