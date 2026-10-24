"""Thin routing layer on Starlette: typed JSON bodies via Pydantic, contract error format, and an
OpenAPI 3.1 document generated from the same models (served at /openapi.json, Swagger UI at /docs).
"""
from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError
from pydantic.json_schema import models_json_schema
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from .errors import ApiError, error_response, pydantic_fields, validation_error
from .schemas import ErrorResponse

log = logging.getLogger("sunwai.web")

Handler = Callable[..., Awaitable[Any]]


@dataclass
class RouteSpec:
    method: str
    path: str
    handler: Handler
    summary: str
    tag: str
    body: type[BaseModel] | None = None
    response: type[BaseModel] | None = None
    status: int = 200
    query: dict[str, str] = field(default_factory=dict)   # name -> description
    kind: str = "json"                                     # json | multipart | sse | file
    errors: tuple[int, ...] = ()
    op_id: str = ""


class Api:
    def __init__(self) -> None:
        self.specs: list[RouteSpec] = []

    def route(self, method: str, path: str, *, summary: str, tag: str, body: type[BaseModel] | None = None,
              response: type[BaseModel] | None = None, status: int = 200, query: dict[str, str] | None = None,
              kind: str = "json", errors: tuple[int, ...] = (), op_id: str = "") -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self.specs.append(RouteSpec(method.upper(), path, fn, summary, tag, body, response, status,
                                        query or {}, kind, errors, op_id or fn.__name__))
            return fn
        return deco

    # ---------------- Starlette routes ----------------
    def starlette_routes(self) -> list[Route]:
        return [Route(s.path, _endpoint(s), methods=[s.method], name=s.op_id) for s in self.specs]

    # ---------------- OpenAPI ----------------
    def openapi(self, title: str, version: str) -> dict[str, Any]:
        models: list[type[BaseModel]] = [ErrorResponse]
        for s in self.specs:
            for m in (s.body, s.response):
                if m is not None and m not in models:
                    models.append(m)
        _, defs = models_json_schema([(m, "serialization") for m in models],
                                     ref_template="#/components/schemas/{model}")
        components = defs.get("$defs", {})

        def ref(m: type[BaseModel]) -> dict[str, str]:
            return {"$ref": f"#/components/schemas/{m.__name__}"}

        paths: dict[str, dict[str, Any]] = {}
        for s in self.specs:
            oa_path = re.sub(r"\{(\w+):\w+\}", r"{\1}", s.path)
            params = []
            for name, conv in re.findall(r"\{(\w+)(?::(\w+))?\}", s.path):
                params.append({"name": name, "in": "path", "required": True,
                               "schema": {"type": "integer" if conv == "int" else "string"}})
            for name, desc in s.query.items():
                params.append({"name": name, "in": "query", "required": False, "description": desc,
                               "schema": {"type": "string"}})
            if s.kind == "sse":
                params.append({"name": "Last-Event-ID", "in": "header", "required": False,
                               "schema": {"type": "string"}})
            op: dict[str, Any] = {"summary": s.summary, "tags": [s.tag], "operationId": s.op_id}
            if params:
                op["parameters"] = params
            if s.kind == "multipart":
                op["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": {
                    "type": "object", "required": ["text"],
                    "properties": {
                        "text": {"type": "string", "minLength": 10, "maxLength": 4000},
                        "language": {"type": "string", "enum": ["en", "hi", "hinglish"]},
                        "files": {"type": "array", "maxItems": 3,
                                  "items": {"type": "string", "format": "binary"}},
                    }}}}}
            elif s.body is not None:
                op["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref(s.body)}}}
            responses: dict[str, Any] = {}
            if s.kind == "sse":
                responses[str(s.status)] = {"description": "Server-Sent Events stream",
                                            "content": {"text/event-stream": {"schema": {"type": "string"}}}}
            elif s.kind == "file":
                responses[str(s.status)] = {"description": "File download",
                                            "content": {"text/markdown": {"schema": {"type": "string"}}}}
            elif s.response is not None:
                responses[str(s.status)] = {"description": "OK",
                                            "content": {"application/json": {"schema": ref(s.response)}}}
            else:
                responses[str(s.status)] = {"description": "OK"}
            for code in sorted(set(s.errors) | {404, 422, 500}):
                responses[str(code)] = {"description": "Error",
                                        "content": {"application/json": {"schema": ref(ErrorResponse)}}}
            paths.setdefault(oa_path, {})[s.method.lower()] = op
        return {
            "openapi": "3.1.0",
            "info": {"title": title, "version": version,
                     "description": "Sunwai backend. Mirrors contracts/API_CONTRACT.md v1.0."},
            "paths": paths,
            "components": {"schemas": components},
        }


def _endpoint(spec: RouteSpec) -> Callable[[Request], Awaitable[Response]]:
    sig = inspect.signature(spec.handler)
    wants = set(sig.parameters)

    async def endpoint(request: Request) -> Response:
        try:
            kwargs: dict[str, Any] = {}
            for k, v in request.path_params.items():
                if k in wants:
                    kwargs[k] = v
            if "request" in wants:
                kwargs["request"] = request
            if spec.body is not None and "body" in wants:
                raw = await request.body()
                if raw.strip():
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        raise ApiError(400, "BAD_REQUEST", "Request body is not valid JSON.")
                else:
                    data = {}
                if not isinstance(data, dict):
                    raise validation_error([{"field": "body", "message": "Expected a JSON object."}])
                try:
                    kwargs["body"] = spec.body.model_validate(data)
                except ValidationError as e:
                    raise validation_error(pydantic_fields(e))
            result = await spec.handler(**kwargs)
            if isinstance(result, Response):
                return result
            if isinstance(result, BaseModel):
                return JSONResponse(result.model_dump(mode="json"), status_code=spec.status)
            return JSONResponse(result, status_code=spec.status)
        except ApiError as e:
            return e.to_response()
        except Exception:  # never leak stack traces to the client
            log.exception("Unhandled error in %s %s", spec.method, spec.path)
            return error_response(500, "INTERNAL", "Something went wrong on our side. Please try again.")

    return endpoint


SWAGGER_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Sunwai API</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url: '/openapi.json', dom_id: '#ui'});</script></body></html>"""


def docs_response() -> HTMLResponse:
    return HTMLResponse(SWAGGER_HTML)
