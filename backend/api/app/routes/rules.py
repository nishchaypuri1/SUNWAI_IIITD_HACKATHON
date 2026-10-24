from .. import schemas
from ..services import rules as rules_service
from . import api


@api.route("GET", "/api/rules/{forum_id}", summary="Current official rule for a forum (E23)", tag="rules",
           response=schemas.Rule)
async def get_rule(forum_id: str) -> schemas.Rule:
    return schemas.Rule(**rules_service.get_rule(forum_id))


@api.route("POST", "/api/rules/{forum_id}/refresh", summary="Re-fetch the official rule live (E24)", tag="rules",
           response=schemas.RunIdResponse, status=202)
async def refresh(forum_id: str) -> schemas.RunIdResponse:
    return schemas.RunIdResponse(run_id=rules_service.start_refresh(forum_id))
