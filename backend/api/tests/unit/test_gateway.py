"""Gateway in live mode against a fake OpenAI-compatible server (httpx.MockTransport)."""
import asyncio
import json

import httpx
import pytest

from app.config import load_settings
from app.errors import ApiError
from app.llm.gateway import Gateway

GOOD_P7 = {"ok": True, "issues": []}


def settings(**env):
    import os
    old = dict(os.environ)
    os.environ.update({"MOCK_MODE": "0", "DEEPSEEK_API_KEY": "k", "GLM_API_KEY": "k", "NEMOTRON_API_KEY": "k",
                       "DEEPSEEK_RPS": "1000", "GLM_RPS": "1000", "NEMOTRON_RPS": "1000", **env})
    try:
        return load_settings()
    finally:
        os.environ.clear()
        os.environ.update(old)


def completion(obj) -> httpx.Response:
    content = obj if isinstance(obj, str) else json.dumps(obj)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def p7_vars():
    return {"case": {}, "subject": "s", "body": "b"}


def run(coro):
    return asyncio.run(coro)


def test_retry_after_on_429(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0.5"})
        return completion(GOOD_P7)

    slept = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        slept.append(s)
        await real_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    g = Gateway(settings(), transport=httpx.MockTransport(handler))
    assert run(g.run("P7", p7_vars())) == GOOD_P7
    assert 0.5 in slept and len(calls) == 2


def test_fallback_to_next_model_on_500():
    seen = []

    def handler(req):
        model = json.loads(req.content)["model"]
        seen.append(model)
        if model.startswith("nvidia"):
            return httpx.Response(500)
        return completion(GOOD_P7)

    g = Gateway(settings(), transport=httpx.MockTransport(handler))
    assert run(g.run("P7", p7_vars())) == GOOD_P7
    stats = g.stats_snapshot()["by_model"]
    assert stats["z-ai/glm-5.3-flash"]["fallbacks"] == 1


def test_bad_json_is_repaired():
    def handler(req):
        msgs = json.loads(req.content)["messages"]
        if "You repair JSON" in msgs[0]["content"]:
            return completion(GOOD_P7)
        return completion("Sure! here you go: {ok: yes")

    g = Gateway(settings(), transport=httpx.MockTransport(handler))
    assert run(g.run("P7", p7_vars())) == GOOD_P7


def test_all_fail_raises_llm_unavailable():
    g = Gateway(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(ApiError) as e:
        run(g.run("P7", p7_vars()))
    assert e.value.code == "LLM_UNAVAILABLE"


def test_cache_and_coalescing():
    n = {"calls": 0}

    async def handler(req):
        n["calls"] += 1
        await asyncio.sleep(0.05)
        return completion(GOOD_P7)

    g = Gateway(settings(), transport=httpx.MockTransport(handler))

    async def both():
        return await asyncio.gather(g.run("P7", p7_vars()), g.run("P7", p7_vars()))
    run(both())
    assert n["calls"] == 1
    run(g.run("P7", p7_vars()))
    assert n["calls"] == 1  # cache hit


def test_images_skipped_for_non_vision_model():
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return completion({"language": "en", "category": "other", "summary": "x", "counterparty": {},
                           "prior_contact": {}})

    g = Gateway(settings(), transport=httpx.MockTransport(handler))
    run(g.run("P1", {"text": "hello there", "today": "2026-10-24"}, images=["data:image/jpeg;base64,AAAA"]))
    user = bodies[0]["messages"][-1]["content"]
    assert isinstance(user, str) and "cannot read images" in user


def test_images_sent_to_vision_model():
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return completion({"language": "en", "category": "other", "summary": "x", "counterparty": {},
                           "prior_contact": {}})

    g = Gateway(settings(GLM_VISION="1"), transport=httpx.MockTransport(handler))
    run(g.run("P1", {"text": "hello there", "today": "2026-10-24"}, images=["data:image/jpeg;base64,AAAA"]))
    parts = bodies[0]["messages"][-1]["content"]
    assert parts[1]["type"] == "image_url"


def test_response_format_dropped_on_400():
    bodies = []

    def handler(req):
        b = json.loads(req.content)
        bodies.append(b)
        if "response_format" in b:
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return completion(GOOD_P7)

    g = Gateway(settings(), transport=httpx.MockTransport(handler))
    assert run(g.run("P7", p7_vars())) == GOOD_P7
    assert "response_format" not in bodies[-1]


def test_mock_mode_validates_mock_brain_output():
    g = Gateway(settings(MOCK_MODE="1"))
    out = run(g.run("P1", {"text": "SBI ne 500 kaat liye 2 Oct ko", "today": "2026-10-24"}))
    assert out["counterparty"]["name"] == "SBI"
