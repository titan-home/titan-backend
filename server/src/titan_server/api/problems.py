"""Errors as application/problem+json (RFC 9457; development rules, 9)."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema
from starlette.exceptions import HTTPException

MEDIA_TYPE = "application/problem+json"
SCHEMAS = "#/components/schemas/"


class FieldError(BaseModel):
    """One invalid field of a request, without the value that was sent."""

    field: str
    message: str


class Problem(BaseModel):
    """An error answer (RFC 9457); every error of the API has this shape."""

    type: str
    title: str
    status: int
    detail: str | None = None
    errors: list[FieldError] | None = None


def problem(
    status: int, detail: str | None = None, errors: list[FieldError] | None = None
) -> JSONResponse:
    """Build a problem response; about:blank means the status code says it all.

    Every error has the type about:blank for now (decision #92).
    """
    body = Problem(
        type="about:blank",
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail or None,
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, media_type=MEDIA_TYPE
    )


def problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Document the errors a route answers, as its responses= argument."""
    return {
        status: {
            "description": HTTPStatus(status).phrase,
            "content": {MEDIA_TYPE: {"schema": {"$ref": SCHEMAS + "Problem"}}},
        }
        for status in statuses
    }


def with_problems(schema: dict[str, Any]) -> dict[str, Any]:
    """Add the Problem schema to an OpenAPI schema and use it for every 422.

    FastAPI documents its own validation error on every route with input; the
    API answers it as a problem instead (validation_error below).
    """
    _, definitions = models_json_schema(
        [(Problem, "serialization")], ref_template=SCHEMAS + "{model}"
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)
    components.update(definitions["$defs"])
    for operations in schema["paths"].values():
        for operation in operations.values():
            if "422" in operation["responses"]:
                operation["responses"]["422"] = problems(422)[422]
    return schema


def add_problem_handlers(app: FastAPI) -> None:
    """Make every error of app a problem+json answer."""

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        """Answer an HTTPException, keeping its headers such as WWW-Authenticate."""
        default = HTTPStatus(error.status_code).phrase
        response = problem(
            error.status_code, None if error.detail == default else error.detail
        )
        response.headers.update(error.headers or {})
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        """Answer invalid input naming the fields, never echoing what was sent.

        FastAPI's own answer repeats every invalid value, a password included.
        """
        fields = [
            FieldError(
                field=".".join(str(part) for part in item["loc"]),
                message=item["msg"],
            )
            for item in error.errors()
        ]
        return problem(422, "The request is not valid.", errors=fields)
