from collections import Counter

from .. import repo, schemas
from ..services import tracking
from . import api


@api.route("POST", "/api/sandbox/attempts", summary="Sandbox page logs an attempt (S1)", tag="sandbox",
           body=schemas.SandboxAttemptRequest, response=schemas.OkResponse)
async def add_attempt(body: schemas.SandboxAttemptRequest) -> schemas.OkResponse:
    repo.add_sandbox_attempt(body.session_id, body.kind)
    return schemas.OkResponse(ok=True)


@api.route("GET", "/api/sandbox/attempts", summary="Sandbox attempt counters (S2)", tag="sandbox",
           response=schemas.SandboxAttemptsSummary)
async def list_attempts() -> schemas.SandboxAttemptsSummary:
    items = repo.sandbox_attempts()
    counts = Counter(i["kind"] for i in items)
    return schemas.SandboxAttemptsSummary(review_reached=counts.get("review_reached", 0),
                                          submit_clicked=counts.get("submit_clicked", 0),
                                          items=[schemas.SandboxAttemptItem(**i) for i in items])


@api.route("DELETE", "/api/sandbox/attempts", summary="Reset sandbox counters (S3)", tag="sandbox",
           response=schemas.OkResponse)
async def clear_attempts() -> schemas.OkResponse:
    repo.clear_sandbox_attempts()
    return schemas.OkResponse(ok=True)


@api.route("GET", "/api/sandbox/status/{complaint_number}", summary="Deterministic fake status (S4)", tag="sandbox",
           response=schemas.SandboxStatus)
async def sandbox_status(complaint_number: str) -> schemas.SandboxStatus:
    return schemas.SandboxStatus(**tracking.sandbox_status(complaint_number))
