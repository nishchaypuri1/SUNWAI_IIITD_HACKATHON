from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import Response

from .. import repo, schemas
from ..errors import ApiError, bad_request, validation_error
from ..services import evidence_pack, intake, planning, serialize, tracking
from . import api


@api.route("GET", "/api/cases", summary="List cases (E6)", tag="cases", response=schemas.CaseList)
async def list_cases() -> schemas.CaseList:
    items = [serialize.summary_out(c, repo.get_steps(c["id"])) for c in repo.list_cases()]
    return schemas.CaseList(items=items)


@api.route("POST", "/api/cases", summary="Create a case from text + screenshots (E7)", tag="cases",
           response=schemas.Case, status=201, kind="multipart", errors=(413, 415, 503))
async def create_case(request: Request) -> schemas.Case:
    ctype = request.headers.get("content-type", "")
    if "multipart/form-data" not in ctype and "application/x-www-form-urlencoded" not in ctype:
        raise bad_request("Send multipart/form-data with fields text, language (optional) and files (optional).")
    try:
        form = await request.form()
    except Exception:
        raise bad_request("Could not read the multipart form.")
    text = form.get("text")
    if not isinstance(text, str) or not (10 <= len(text.strip()) <= 4000):
        raise validation_error([{"field": "text", "message": "Describe the problem in 10 to 4000 characters."}])
    language = form.get("language") or None
    if language is not None and language not in ("en", "hi", "hinglish"):
        raise validation_error([{"field": "language", "message": "Must be en, hi or hinglish."}])
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile) and (f.filename or f.size)]
    if len(files) > 3:
        raise validation_error([{"field": "files", "message": "At most 3 images."}])
    images = []
    for f in files:
        data = await f.read()
        if len(data) > intake.MAX_BYTES:
            raise ApiError(413, "FILE_TOO_LARGE", f"{f.filename or 'File'} is larger than 5 MB.")
        images.append(intake.process_image(f.content_type, data, f.filename or ""))
    case = await intake.create_case(text.strip(), language, images)
    return serialize.case_out(case, [])


@api.route("GET", "/api/cases/{case_id}", summary="Get a case (E10)", tag="cases", response=schemas.Case)
async def get_case(case_id: str) -> schemas.Case:
    return serialize.case_out(repo.get_case(case_id))


@api.route("POST", "/api/cases/{case_id}/answers", summary="Answer follow-up questions (E8)", tag="cases",
           body=schemas.AnswersRequest, response=schemas.Case, errors=(409,))
async def answers(case_id: str, body: schemas.AnswersRequest) -> schemas.Case:
    case = await intake.apply_answers(case_id, body.answers)
    return serialize.case_out(case)


@api.route("POST", "/api/cases/{case_id}/plan", summary="Plan the escalation ladder (E9)", tag="cases",
           response=schemas.Case, errors=(409, 503))
async def plan(case_id: str) -> schemas.Case:
    case = await planning.plan_case(case_id)
    return serialize.case_out(case)


@api.route("POST", "/api/cases/{case_id}/close", summary="Close a case (E21)", tag="cases",
           body=schemas.CloseRequest, response=schemas.Case, errors=(409,))
async def close(case_id: str, body: schemas.CloseRequest) -> schemas.Case:
    case = await tracking.close_case(case_id, body.reason)
    return serialize.case_out(case)


@api.route("GET", "/api/cases/{case_id}/evidence-pack", summary="Evidence pack download (E25)", tag="cases",
           query={"format": "md (default) or pdf (not available yet)"}, kind="file", errors=(400,))
async def evidence(case_id: str, request: Request) -> Response:
    fmt = request.query_params.get("format", "md")
    if fmt == "pdf":
        raise bad_request("PDF export is not available yet. Use format=md.")
    if fmt != "md":
        raise bad_request("format must be md or pdf.")
    md = evidence_pack.build_markdown(case_id)
    return Response(md, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="sunwai-{case_id}.md"'})
