from .. import repo, schemas
from ..services import prefill, serialize
from . import api


@api.route("GET", "/api/runs/{run_id}", summary="Run detail with events (E16)", tag="runs", response=schemas.RunDetail)
async def get_run(run_id: str) -> schemas.RunDetail:
    return serialize.run_detail(repo.get_run(run_id))


@api.route("POST", "/api/runs/{run_id}/cancel", summary="Cancel a run (E17)", tag="runs", response=schemas.OkResponse)
async def cancel_run(run_id: str) -> schemas.OkResponse:
    prefill.cancel(run_id)
    return schemas.OkResponse(ok=True)
