"""The FastAPI application of the TITAN API."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the API application with every route mounted."""
    # The contract is generated from this app (decision #87), so nothing that
    # is not part of /api/v1 may show up in the schema; the interactive docs
    # stay off on a node.
    app = FastAPI(title="TITAN API", version="1", docs_url=None, redoc_url=None)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        """Tell the controller the API is up."""
        return {"status": "ok"}

    return app
