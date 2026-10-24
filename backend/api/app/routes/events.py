import asyncio

from starlette.requests import Request
from starlette.responses import StreamingResponse

from .. import repo
from ..events import bus, sse_format
from . import api

PING_SECONDS = 15


@api.route("GET", "/api/cases/{case_id}/events", summary="Server-Sent Events for a case (E22)", tag="events",
           query={"since": "replay events with id greater than this"}, kind="sse")
async def stream(case_id: str, request: Request) -> StreamingResponse:
    repo.get_case(case_id)  # 404 before opening the stream
    raw = request.headers.get("last-event-id") or request.query_params.get("since") or "0"
    try:
        since = int(raw)
    except ValueError:
        since = 0
    queue = bus.subscribe(case_id)

    async def gen():
        last = since
        try:
            yield "retry: 3000\n\n"
            for evt in bus.since(case_id, since):
                last = evt["id"]
                yield sse_format(evt)
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
                    continue
                if evt["id"] <= last:
                    continue
                last = evt["id"]
                yield sse_format(evt)
        finally:
            bus.unsubscribe(case_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
