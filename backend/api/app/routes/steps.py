from starlette.requests import Request

from .. import repo, schemas
from ..services import discovery, drafting, escalation, prefill, serialize, tracking
from . import api

S = "/api/cases/{case_id}/steps/{n:int}"


@api.route("POST", S + "/discover", summary="Find the company's grievance route (E11)", tag="steps",
           response=schemas.RunIdResponse, status=202, errors=(409,))
async def discover(case_id: str, n: int) -> schemas.RunIdResponse:
    return schemas.RunIdResponse(run_id=await discovery.start(case_id, n))


@api.route("POST", S + "/draft", summary="Generate a draft (E12)", tag="steps", response=schemas.Draft,
           errors=(409, 503))
async def make_draft(case_id: str, n: int) -> schemas.Draft:
    repo.get_case(case_id)
    return schemas.Draft(**await drafting.generate(case_id, n))


@api.route("PUT", S + "/draft", summary="Save an edited draft (E13)", tag="steps", body=schemas.DraftUpdateRequest,
           response=schemas.Draft, errors=(409,))
async def edit_draft(case_id: str, n: int, body: schemas.DraftUpdateRequest) -> schemas.Draft:
    return schemas.Draft(**await drafting.update(case_id, n, body.subject, body.body))


@api.route("GET", S + "/prefill/preview", summary="Preview what the agent will type (E14)", tag="steps",
           query={"portal": "sandbox (default) or live"}, response=schemas.PrefillPreview, errors=(400, 409, 503))
async def preview(case_id: str, n: int, request: Request) -> schemas.PrefillPreview:
    portal = request.query_params.get("portal", "sandbox")
    return schemas.PrefillPreview(**await prefill.preview(case_id, n, portal))


@api.route("POST", S + "/prefill", summary="Approve and start the agent pre-fill (E15)", tag="steps",
           body=schemas.PrefillRequest, response=schemas.RunIdResponse, status=202, errors=(400, 409, 500, 503))
async def start_prefill(case_id: str, n: int, body: schemas.PrefillRequest) -> schemas.RunIdResponse:
    return schemas.RunIdResponse(run_id=await prefill.start(case_id, n, body.approved, body.portal))


@api.route("POST", S + "/submitted", summary="User submitted on the portal; start the clock (E18)", tag="steps",
           body=schemas.SubmittedRequest, response=schemas.Case, errors=(409,))
async def submitted(case_id: str, n: int, body: schemas.SubmittedRequest) -> schemas.Case:
    case = await tracking.mark_submitted(case_id, n, body.ack_number, body.submitted_at)
    return serialize.case_out(case)


@api.route("POST", S + "/check-status", summary="Check complaint status with the agent (E19)", tag="steps",
           body=schemas.CheckStatusRequest, response=schemas.RunIdResponse, status=202, errors=(400, 409))
async def check_status(case_id: str, n: int, body: schemas.CheckStatusRequest) -> schemas.RunIdResponse:
    return schemas.RunIdResponse(run_id=await tracking.start_status_check(case_id, n, body.portal))


@api.route("POST", S + "/prepare-next", summary="Prepare the next filing (E20)", tag="steps",
           response=schemas.EscalationPack, errors=(409, 503))
async def prepare_next(case_id: str, n: int) -> schemas.EscalationPack:
    return schemas.EscalationPack(**await escalation.prepare_next(case_id, n))
