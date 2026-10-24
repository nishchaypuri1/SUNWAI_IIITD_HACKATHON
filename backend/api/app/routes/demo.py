from .. import clock, repo, schemas, seed
from ..errors import validation_error
from ..services import planning
from . import api


@api.route("GET", "/api/demo/scenarios", summary="Demo scenarios (E2)", tag="demo", response=schemas.ScenarioList)
async def scenarios() -> schemas.ScenarioList:
    return schemas.ScenarioList(items=[schemas.Scenario(**s) for s in seed.scenarios()])


@api.route("GET", "/api/demo/clock", summary="Demo clock (E3)", tag="demo", response=schemas.DemoClock)
async def get_clock() -> schemas.DemoClock:
    return schemas.DemoClock(**clock.snapshot())


@api.route("POST", "/api/demo/clock", summary="Advance or reset the demo clock (E4)", tag="demo",
           body=schemas.ClockRequest, response=schemas.DemoClock)
async def set_clock(body: schemas.ClockRequest) -> schemas.DemoClock:
    if body.reset:
        clock.reset()
    elif body.advance_days is not None:
        clock.advance(body.advance_days)
    else:
        raise validation_error([{"field": "body", "message": "Send {advance_days: n} or {reset: true}."}])
    planning.sweep()   # synchronous so step_due events are emitted before we answer
    return schemas.DemoClock(**clock.snapshot())


@api.route("GET", "/api/forums", summary="Forums (E5)", tag="reference", response=schemas.ForumList)
async def forums() -> schemas.ForumList:
    return schemas.ForumList(items=[schemas.Forum(**f) for f in repo.all_forums()])
