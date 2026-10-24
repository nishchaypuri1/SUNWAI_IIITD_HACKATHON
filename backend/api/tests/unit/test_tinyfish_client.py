"""TinyFish client in live mode against a fake server (httpx.MockTransport)."""
import asyncio
import json

import httpx
import pytest

from app.config import load_settings
from app.tinyfish.client import TinyFishClient, TinyFishError


def settings():
    import os
    old = dict(os.environ)
    os.environ.update({"MOCK_MODE": "0", "TINYFISH_API_KEY": "tf_test"})
    try:
        return load_settings()
    finally:
        os.environ.clear()
        os.environ.update(old)


def run(c):
    return asyncio.run(c)


def test_search_falls_back_to_us_location():
    seen = []

    def handler(req):
        assert req.headers["X-API-Key"] == "tf_test"
        seen.append(req.url.params.get("location"))
        if req.url.params.get("location") == "IN":
            return httpx.Response(400, json={"error": {"code": "INVALID_INPUT", "message": "bad location"}})
        return httpx.Response(200, json={"query": "q", "results": [{"position": 1, "title": "T", "url": "https://x.gov.in",
                                                                     "snippet": "s", "site_name": "x"}]})

    c = TinyFishClient(settings(), transport=httpx.MockTransport(handler))
    res = run(c.search("q"))
    assert seen == ["IN", "US"] and res[0]["url"] == "https://x.gov.in"


def test_fetch_tolerant_fields():
    def handler(req):
        body = json.loads(req.content)
        assert body["ttl"] == 0
        return httpx.Response(200, json={"results": [{"url": "u1", "markdown": "M"}, {"url": "u2", "text": "T"}],
                                         "errors": [{"url": "u3", "error": "page_not_found", "status": 404}]})

    c = TinyFishClient(settings(), transport=httpx.MockTransport(handler))
    out = run(c.fetch(["u1", "u2", "u3"]))
    assert [r["text"] for r in out["results"]] == ["M", "T"] and out["errors"][0]["url"] == "u3"


SSE = (b'data: {"type":"STARTED","run_id":"r1","timestamp":"2026-10-24T00:00:00Z"}\n\n'
       b'data: {"type":"STREAMING_URL","run_id":"r1","streaming_url":"https://s","timestamp":"t"}\n\n'
       b': keepalive\n\n'
       b'data: {"type":"PROGRESS","run_id":"r1","purpose":"Typing","timestamp":"t"}\n\n'
       b'data: {"type":"HEARTBEAT","timestamp":"t"}\n\n'
       b'data: {"type":"COMPLETE","run_id":"r1","status":"COMPLETED","result":{"ok":true},"timestamp":"t"}\n\n')


def test_run_sse_streams_events_and_returns_complete():
    def handler(req):
        body = json.loads(req.content)
        assert body["agent_config"]["max_steps"] == 60 and body["output_schema"]["type"] == "object"
        return httpx.Response(200, content=SSE, headers={"content-type": "text/event-stream"})

    got = []

    async def on_event(e):
        got.append(e["type"])

    c = TinyFishClient(settings(), transport=httpx.MockTransport(handler))
    complete = run(c.run_sse("https://portal", "goal", on_event=on_event, output_schema={"type": "object"},
                             agent_config={"max_steps": 60}))
    assert complete["result"] == {"ok": True}
    assert got == ["STARTED", "STREAMING_URL", "PROGRESS", "HEARTBEAT", "COMPLETE"]


def test_missing_complete_recovers_with_get_run():
    def handler(req):
        if req.url.path.endswith("/run-sse"):
            return httpx.Response(200, content=SSE.split(b'data: {"type":"COMPLETE"')[0])
        assert req.url.path == "/v1/runs/r1"
        return httpx.Response(200, json={"run_id": "r1", "status": "COMPLETED", "result": {"recovered": 1}})

    async def noop(e):
        pass

    c = TinyFishClient(settings(), transport=httpx.MockTransport(handler))
    complete = run(c.run_sse("https://p", "g", on_event=noop))
    assert complete["result"] == {"recovered": 1}


def test_missing_complete_and_running_is_timeout():
    def handler(req):
        if req.url.path.endswith("/run-sse"):
            return httpx.Response(200, content=b'data: {"type":"STARTED","run_id":"r2"}\n\n')
        return httpx.Response(200, json={"run_id": "r2", "status": "RUNNING"})

    async def noop(e):
        pass

    c = TinyFishClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(TinyFishError) as e:
        run(c.run_sse("https://p", "g", on_event=noop))
    assert e.value.code == "TIMEOUT"


@pytest.mark.parametrize("status,code", [(401, "INVALID_API_KEY"), (402, "INSUFFICIENT_CREDITS"),
                                         (429, "RATE_LIMIT_EXCEEDED")])
def test_error_mapping(status, code):
    c = TinyFishClient(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(status, json={})))
    with pytest.raises(TinyFishError) as e:
        run(c.search("q"))
    assert e.value.code == code


def test_cancel_path():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path))
        return httpx.Response(200, json={"run_id": "r9", "status": "CANCELLED"})

    run(TinyFishClient(settings(), transport=httpx.MockTransport(handler)).cancel("r9"))
    assert seen == [("POST", "/v1/runs/r9/cancel")]


def test_missing_key():
    import os
    os.environ["MOCK_MODE"] = "0"
    s = load_settings()
    os.environ["MOCK_MODE"] = "1"
    s.tinyfish_api_key = ""
    with pytest.raises(TinyFishError) as e:
        run(TinyFishClient(s).search("q"))
    assert e.value.code == "MISSING_API_KEY"
