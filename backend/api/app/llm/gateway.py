"""LLM gateway: the ONLY place that talks to language models.

- Role-based fallback chains (intake / reason / fast) over OpenAI-compatible endpoints (OpenRouter by default).
- JSON-schema validation of every output; one repair pass with P8 on the fast role; then next model.
- Honors Retry-After on 429; per-provider concurrency + rate spacing; optional extra_body dropped on HTTP 400.
- In-flight coalescing and an in-memory cache (never for inputs with PII flags or images).
- Stats for /api/debug/llm-stats.
- MOCK_MODE=1: recorded fixture (llm/fixtures/{prompt}/{sha}.json) if present, else the deterministic mock brain.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import statistics
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any

import httpx
import jsonschema

from ..config import ProviderConfig, Settings, get_settings
from ..errors import ApiError
from . import mock_brain
from .prompts import PROMPTS, build_messages

log = logging.getLogger("sunwai.llm")
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class _Provider:
    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.sem = asyncio.Semaphore(max(1, cfg.max_concurrency))
        self.min_interval = 1.0 / cfg.rps if cfg.rps > 0 else 0.0
        self._last = 0.0
        self._lock = asyncio.Lock()
        self.available: bool | None = None       # set by check_models()
        self.extra_body: dict | None = None
        self.no_response_format = False

    async def pace(self) -> None:
        async with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class _Retryable(Exception):
    pass


class Gateway:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self.providers = {name: _Provider(cfg) for name, cfg in self.settings.providers.items()}
        self.roles = {"intake": self.settings.role_intake, "reason": self.settings.role_reason,
                      "fast": self.settings.role_fast}
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._inflight: dict[str, asyncio.Future] = {}
        self.stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "fallbacks": 0, "errors": 0,
                                                                     "lat": []})
        self.total_calls = 0

    # ------------------------------------------------------------ public
    async def run(self, prompt_id: str, variables: dict[str, Any], *, images: list[str] | None = None,
                  cacheable: bool = True) -> dict:
        spec = PROMPTS[prompt_id]
        messages = build_messages(prompt_id, variables)
        key = hashlib.sha256((prompt_id + json.dumps(messages, ensure_ascii=False, sort_keys=True)).encode()
                             ).hexdigest()
        use_cache = cacheable and not images
        if use_cache and key in self._cache:
            self._cache.move_to_end(key)
            return json.loads(json.dumps(self._cache[key]))
        if key in self._inflight:
            return json.loads(json.dumps(await asyncio.shield(self._inflight[key])))
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await self._run_uncached(prompt_id, spec, variables, messages, images, key)
            fut.set_result(result)
            if use_cache:
                self._cache[key] = result
                if len(self._cache) > 500:
                    self._cache.popitem(last=False)
            return json.loads(json.dumps(result))
        except BaseException as e:
            if not fut.done():
                fut.set_exception(e)
                fut.exception()  # mark retrieved
            raise
        finally:
            self._inflight.pop(key, None)

    def health_models(self) -> dict[str, dict[str, Any]]:
        out = {}
        for role, chain in self.roles.items():
            prov = self.providers.get(chain[0]) if chain else None
            primary = prov.cfg.model if prov else "unconfigured"
            if self.settings.mock_mode:
                available = True
            else:
                provs = [self.providers.get(n) for n in chain]
                available = any(p is not None and bool(p.cfg.api_key) and p.available is not False for p in provs)
            out[role] = {"primary": primary, "available": available}
        return out

    def stats_snapshot(self) -> dict[str, Any]:
        by_model = {}
        for model, s in self.stats.items():
            lat = s["lat"]
            by_model[model] = {"calls": s["calls"], "fallbacks": s["fallbacks"], "errors": s["errors"],
                               "p50_ms": round(statistics.median(lat), 1) if lat else 0.0}
        return {"calls": self.total_calls, "by_model": by_model}

    async def check_models(self) -> None:
        """Startup check: is each configured model id listed by its provider's GET /models?"""
        if self.settings.mock_mode:
            return
        async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
            for p in self.providers.values():
                if not p.cfg.api_key:
                    p.available = False
                    log.warning("LLM provider %s has no API key; role entries using it are unavailable", p.cfg.name)
                    continue
                try:
                    r = await client.get(f"{p.cfg.base_url}/models",
                                         headers={"Authorization": f"Bearer {p.cfg.api_key}"})
                    if r.status_code in (401, 403):
                        p.available = False
                        log.warning("LLM provider %s rejected the API key (HTTP %s)", p.cfg.name, r.status_code)
                        continue
                    if r.status_code != 200:
                        log.warning("Model check for %s returned HTTP %s; will still try it", p.cfg.name,
                                    r.status_code)
                        continue
                    ids = {m.get("id") for m in r.json().get("data", [])}
                    p.available = p.cfg.model in ids
                    if not p.available:
                        log.warning("Model %s is not listed by %s /models; the role falls back to the next model",
                                    p.cfg.model, p.cfg.name)
                except Exception as e:  # unknown, not unavailable: network trouble must not disable the LLM
                    log.warning("Model check failed for %s (%s); will still try it", p.cfg.name, type(e).__name__)

    # ------------------------------------------------------------ internals
    async def _run_uncached(self, prompt_id: str, spec: Any, variables: dict, messages: list, images: list[str] | None,
                            key: str) -> dict:
        self.total_calls += 1
        if self.settings.mock_mode:
            return self._mock(prompt_id, variables, key)
        chain = [self.providers[n] for n in self.roles.get(spec.role, []) if n in self.providers]
        last_err = "no provider configured"
        for idx, prov in enumerate(chain):
            if not prov.cfg.api_key or prov.available is False:
                continue
            stat = self.stats[prov.cfg.model]
            if idx > 0:
                stat["fallbacks"] += 1
            try:
                text = await self._call(prov, messages, spec.temperature, spec.max_tokens, images)
                data = _parse_json(text)
                if data is None or not _valid(data, spec.schema):
                    data = await self._repair(text, spec.schema)
                if data is not None and _valid(data, spec.schema):
                    self._record_fixture(prompt_id, key, data)
                    return data
                last_err = f"{prov.cfg.model}: invalid JSON after repair"
                stat["errors"] += 1
            except Exception as e:
                stat["errors"] += 1
                last_err = f"{prov.cfg.model}: {type(e).__name__}: {e}"[:300]
                log.warning("LLM call failed (%s) on %s", type(e).__name__, prov.cfg.model)
        log.error("All models failed for %s: %s", prompt_id, last_err)
        raise ApiError(503, "LLM_UNAVAILABLE", "The language model is unavailable right now. Please try again "
                       "in a moment (or run the backend with MOCK_MODE=1).")

    def _mock(self, prompt_id: str, variables: dict, key: str) -> dict:
        start = time.monotonic()
        path = FIXTURE_DIR / prompt_id / f"{key[:16]}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            model = "fixture"
        else:
            data = mock_brain.run(prompt_id, variables)
            model = "mock-brain"
        schema = PROMPTS[prompt_id].schema if prompt_id != "P8" else None
        if schema is not None:
            jsonschema.validate(data, schema)
        s = self.stats[model]
        s["calls"] += 1
        s["lat"].append((time.monotonic() - start) * 1000)
        return data

    async def _repair(self, broken: str, schema: dict) -> dict | None:
        for name in self.roles.get("fast", []):
            prov = self.providers.get(name)
            if not prov or not prov.cfg.api_key or prov.available is False:
                continue
            try:
                msgs = build_messages("P8", {"schema": schema, "broken": broken})
                text = await self._call(prov, msgs, 0.0, 1500, None)
                return _parse_json(text)
            except Exception:
                return None
        return None

    async def _call(self, prov: _Provider, messages: list, temperature: float, max_tokens: int,
                    images: list[str] | None) -> str:
        msgs = [dict(m) for m in messages]
        if images:
            if prov.cfg.vision:
                parts: list[dict] = [{"type": "text", "text": msgs[-1]["content"]}]
                parts += [{"type": "image_url", "image_url": {"url": u}} for u in images]
                msgs[-1]["content"] = parts
            else:
                msgs[-1]["content"] += ("\n(Screenshots were attached but this model cannot read images; "
                                        "use the text only.)")
        body: dict[str, Any] = {"model": prov.cfg.model, "messages": msgs, "temperature": temperature,
                                "max_tokens": max_tokens}
        if not prov.no_response_format:
            body["response_format"] = {"type": "json_object"}
        if prov.extra_body:
            body.update(prov.extra_body)
        headers = {"Authorization": f"Bearer {prov.cfg.api_key}", "Content-Type": "application/json",
                   "X-Title": "Sunwai"}
        stat = self.stats[prov.cfg.model]
        async with prov.sem:
            for attempt in range(3):
                await prov.pace()
                start = time.monotonic()
                async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), transport=self.transport) as c:
                    r = await c.post(f"{prov.cfg.base_url}/chat/completions", json=body, headers=headers)
                stat["calls"] += 1
                stat["lat"].append((time.monotonic() - start) * 1000)
                if r.status_code == 429 and attempt < 2:
                    delay = _retry_after(r.headers.get("Retry-After"))
                    log.info("429 from %s; retrying after %.1fs", prov.cfg.model, delay)
                    await asyncio.sleep(delay)
                    continue
                if r.status_code == 400 and attempt < 2 and (prov.extra_body or "response_format" in body):
                    if prov.extra_body:
                        for k in prov.extra_body:
                            body.pop(k, None)
                        prov.extra_body = None
                    elif "response_format" in body:
                        body.pop("response_format")
                        prov.no_response_format = True
                    continue
                if r.status_code >= 500 and attempt < 1:
                    await asyncio.sleep(1.0)
                    continue
                if r.status_code != 200:
                    raise _Retryable(f"HTTP {r.status_code}")
                data = r.json()
                return data["choices"][0]["message"].get("content") or ""
        raise _Retryable("exhausted retries")

    def _record_fixture(self, prompt_id: str, key: str, data: dict) -> None:
        if not self.settings.record_fixtures:
            return
        path = FIXTURE_DIR / prompt_id / f"{key[:16]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _retry_after(v: str | None) -> float:
    try:
        return max(0.5, min(20.0, float(v))) if v else 2.0
    except ValueError:
        return 2.0


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        pass
    s, e = t.find("{"), t.rfind("}")
    if s >= 0 and e > s:
        try:
            v = json.loads(t[s:e + 1])
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _valid(data: dict, schema: dict) -> bool:
    try:
        jsonschema.validate(data, schema)
        return True
    except jsonschema.ValidationError:
        return False


_gateway: Gateway | None = None


def gateway() -> Gateway:
    global _gateway
    if _gateway is None:
        _gateway = Gateway()
    return _gateway


def reset_gateway(g: Gateway | None = None) -> None:
    global _gateway
    _gateway = g
