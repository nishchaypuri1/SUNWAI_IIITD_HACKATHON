"""TinyFish client: the ONLY place that talks to TinyFish (Search, Fetch, Agent run-sse/run-async, runs).

Endpoints and field names verified against docs.tinyfish.ai on 2026-10-24 (see docs/VERIFIED.md):
  Search  GET  https://api.search.tinyfish.ai?query=&location=&language=   -> {query, results[{position, site_name,
          title, snippet, url, ...}], total_results, page}
  Fetch   POST https://api.fetch.tinyfish.ai {urls[<=10], format, ttl}      -> {results[{url, final_url, title, text,
          ...}], errors[{url, error, status}]}
  Agent   POST /v1/automation/run-sse | /v1/automation/run-async;  GET /v1/runs/{id};  POST /v1/runs/{id}/cancel
MOCK_MODE=1 replays recorded fixtures with realistic delays (scaled by MOCK_DELAY_SCALE).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from ..config import Settings, get_settings
from .sse import SSEDecoder, parse_lines

log = logging.getLogger("sunwai.tinyfish")
FIXTURES = Path(__file__).resolve().parent / "fixtures"

OnEvent = Callable[[dict], Awaitable[None]]


class TinyFishError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status = status


def _map_http_error(status: int, body: bytes | str) -> TinyFishError:
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        code, msg = err.get("code") or "", err.get("message") or ""
    except (ValueError, AttributeError):
        code, msg = "", str(body)[:200]
    if status == 401:
        return TinyFishError(code or "INVALID_API_KEY", msg or "Invalid TinyFish API key", status=status)
    if status == 402:
        return TinyFishError(code or "INSUFFICIENT_CREDITS", msg or "TinyFish credits exhausted", status=status)
    if status == 429:
        return TinyFishError(code or "RATE_LIMIT_EXCEEDED", msg or "TinyFish rate limit", retryable=True, status=status)
    if status >= 500:
        return TinyFishError(code or "SERVICE_BUSY", msg or f"TinyFish HTTP {status}", retryable=True, status=status)
    return TinyFishError(code or "INVALID_INPUT", msg or f"TinyFish HTTP {status}", status=status)


class TinyFishClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self.last_error_code: str | None = None

    # ------------------------------------------------------------ helpers
    @property
    def mock(self) -> bool:
        return self.settings.mock_mode

    def _headers(self) -> dict[str, str]:
        key = self.settings.tinyfish_api_key
        if not key:
            raise TinyFishError("MISSING_API_KEY", "TINYFISH_API_KEY is not set")
        return {"X-API-Key": key, "Content-Type": "application/json"}

    def _client(self, timeout: httpx.Timeout | float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self.transport)

    async def _request(self, method: str, url: str, *, timeout: float, retry_5xx: bool = True, **kw: Any) -> Any:
        headers = self._headers()
        for attempt in range(2):
            try:
                async with self._client(timeout) as c:
                    r = await c.request(method, url, headers=headers, **kw)
            except httpx.TimeoutException:
                if attempt == 0 and retry_5xx:
                    continue
                raise TinyFishError("TIMEOUT", "TinyFish request timed out", retryable=True)
            except httpx.TransportError as e:
                if attempt == 0 and retry_5xx:
                    continue
                raise TinyFishError("BACKEND_UNAVAILABLE", f"Cannot reach TinyFish: {type(e).__name__}",
                                    retryable=True)
            if r.status_code >= 500 and attempt == 0 and retry_5xx:
                await asyncio.sleep(1.0)
                continue
            if r.status_code >= 400:
                err = _map_http_error(r.status_code, r.content)
                self.last_error_code = err.code
                raise err
            self.last_error_code = None
            return r.json()
        raise TinyFishError("SERVICE_BUSY", "TinyFish unavailable after retry", retryable=True)

    # ------------------------------------------------------------ Search
    async def search(self, query: str, location: str | None = None, language: str = "en") -> list[dict]:
        if self.mock:
            return _mock_search(query)
        loc = location or self.settings.tinyfish_search_location
        params = {"query": query, "language": language}
        if loc:
            params["location"] = loc
        try:
            data = await self._request("GET", self.settings.tinyfish_search_url, params=params, timeout=10)
        except TinyFishError as e:
            if e.status == 400 and loc and loc != "US":
                log.info("Search rejected location=%s; retrying with US", loc)
                params["location"] = "US"
                data = await self._request("GET", self.settings.tinyfish_search_url, params=params, timeout=10)
            else:
                raise
        out = []
        for r in data.get("results") or []:
            if r.get("url"):
                out.append({"title": r.get("title") or "", "url": r["url"], "snippet": r.get("snippet") or "",
                            "site_name": r.get("site_name") or ""})
        return out

    # ------------------------------------------------------------ Fetch
    async def fetch(self, urls: list[str], ttl: int = 0) -> dict:
        if self.mock:
            return _mock_fetch(urls)
        data = await self._request("POST", self.settings.tinyfish_fetch_url,
                                   json={"urls": urls[:10], "format": "markdown", "ttl": ttl}, timeout=150)
        results = []
        for r in data.get("results") or []:
            text = r.get("text") or r.get("markdown") or r.get("content") or ""
            results.append({"url": r.get("url"), "final_url": r.get("final_url") or r.get("url"),
                            "title": r.get("title") or "", "text": text})
        return {"results": results, "errors": data.get("errors") or []}

    # ------------------------------------------------------------ Agent
    async def run_sse(self, url: str, goal: str, *, on_event: OnEvent, output_schema: dict | None = None,
                      agent_config: dict | None = None, capture_config: dict | None = None,
                      browser_profile: str | None = None, proxy_country: str | None = None,
                      mock_fixture: str = "fill_sandbox", mock_result: dict | None = None) -> dict:
        """Stream an agent run, calling on_event for every decoded event. Returns the COMPLETE event."""
        if self.mock:
            return await self._mock_run(mock_fixture, on_event, mock_result)
        body: dict[str, Any] = {"url": url, "goal": goal,
                                "browser_profile": browser_profile or self.settings.tinyfish_browser_profile}
        if output_schema:
            body["output_schema"] = output_schema
        if agent_config:
            body["agent_config"] = agent_config
        if capture_config:
            body["capture_config"] = capture_config
        if proxy_country:
            body["proxy_config"] = {"enabled": True, "country_code": proxy_country}
        try:
            return await self._stream(body, on_event)
        except TinyFishError as e:
            if proxy_country and e.code == "INVALID_INPUT":
                log.info("Agent run rejected proxy_config; retrying without proxy")
                body.pop("proxy_config", None)
                return await self._stream(body, on_event)
            if e.retryable and e.code in ("SERVICE_BUSY", "BACKEND_UNAVAILABLE"):
                await asyncio.sleep(1.5)
                return await self._stream(body, on_event)
            raise

    async def _stream(self, body: dict, on_event: OnEvent) -> dict:
        headers = self._headers()
        headers["Accept"] = "text/event-stream"
        url = f"{self.settings.tinyfish_agent_base}/v1/automation/run-sse"
        dec = SSEDecoder()
        complete: dict | None = None
        run_id: str | None = None
        raw_lines: list[str] = []
        timeout = httpx.Timeout(connect=10, read=None, write=30, pool=10)
        try:
            async with self._client(timeout) as c:
                async with c.stream("POST", url, json=body, headers=headers) as resp:
                    if resp.status_code >= 400:
                        err = _map_http_error(resp.status_code, await resp.aread())
                        self.last_error_code = err.code
                        raise err
                    async for line in resp.aiter_lines():
                        if self.settings.record_fixtures:
                            raw_lines.append(line)
                        for evt in dec.feed(line):
                            run_id = run_id or evt.get("run_id")
                            await on_event(evt)
                            if evt.get("type") == "COMPLETE":
                                complete = evt
                    for evt in dec.flush():
                        run_id = run_id or evt.get("run_id")
                        await on_event(evt)
                        if evt.get("type") == "COMPLETE":
                            complete = evt
        except httpx.TransportError as e:
            if run_id is None:
                raise TinyFishError("BACKEND_UNAVAILABLE", f"Agent stream failed: {type(e).__name__}",
                                    retryable=True)
            log.warning("Agent stream dropped (%s); trying to recover run %s", type(e).__name__, run_id)
        finally:
            if raw_lines and self.settings.record_fixtures:
                self._save_raw(run_id or uuid.uuid4().hex, raw_lines)
        self.last_error_code = None
        if complete is None:
            if run_id:
                try:
                    run = await self.get_run(run_id)
                    if run.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
                        complete = {"type": "COMPLETE", "run_id": run_id, "status": run["status"],
                                    "result": run.get("result"), "error": run.get("error"), "recovered": True}
                        await on_event(complete)
                except TinyFishError:
                    pass
            if complete is None:
                raise TinyFishError("TIMEOUT", "The agent stream ended without a final result", retryable=True)
        return complete

    def _save_raw(self, run_id: str, lines: list[str]) -> None:
        path = FIXTURES / "live" / f"{run_id}.sse"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    async def run_async(self, url: str, goal: str, **kw: Any) -> str:
        if self.mock:
            return f"tf_mock_{uuid.uuid4().hex[:10]}"
        body = {"url": url, "goal": goal, **{k: v for k, v in kw.items() if v is not None}}
        data = await self._request("POST", f"{self.settings.tinyfish_agent_base}/v1/automation/run-async",
                                   json=body, timeout=30)
        return data.get("run_id") or data.get("id")

    async def get_run(self, run_id: str, screenshots: str = "url") -> dict:
        if self.mock or run_id.startswith("tf_mock_"):
            return {"run_id": run_id, "status": "COMPLETED", "steps": [], "video_url": None, "streaming_url": None}
        return await self._request("GET", f"{self.settings.tinyfish_agent_base}/v1/runs/{run_id}",
                                   params={"screenshots": screenshots}, timeout=20)

    async def cancel(self, run_id: str) -> None:
        if self.mock or run_id.startswith("tf_mock_"):
            return
        await self._request("POST", f"{self.settings.tinyfish_agent_base}/v1/runs/{run_id}/cancel", timeout=15,
                            retry_5xx=False)

    # ------------------------------------------------------------ mock replay
    async def _mock_run(self, fixture: str, on_event: OnEvent, mock_result: dict | None) -> dict:
        path = FIXTURES / "sse" / f"{fixture}.sse"
        events = list(parse_lines(path.read_text(encoding="utf-8").splitlines()))
        tf_id = f"tf_mock_{uuid.uuid4().hex[:10]}"
        scale = max(0.0, self.settings.mock_delay_scale)
        prev_ts: float | None = None
        total = 0.0
        complete: dict | None = None
        for evt in events:
            ts = _ts(evt.get("timestamp"))
            if prev_ts is not None and ts is not None and scale > 0:
                delay = min(2.5, max(0.0, ts - prev_ts)) * scale
                if total + delay > 45:
                    delay = max(0.0, 45 - total)
                total += delay
                if delay:
                    await asyncio.sleep(delay)
            prev_ts = ts if ts is not None else prev_ts
            evt = dict(evt)
            if "run_id" in evt:
                evt["run_id"] = tf_id
            evt["timestamp"] = datetime.now().astimezone().isoformat(timespec="seconds")
            if evt.get("type") == "COMPLETE" and mock_result is not None:
                evt["result"] = mock_result
            await on_event(evt)
            if evt.get("type") == "COMPLETE":
                complete = evt
        if complete is None:
            raise TinyFishError("TIMEOUT", "Mock fixture has no COMPLETE event", retryable=False)
        return complete


def _ts(v: Any) -> float | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _mock_search(query: str) -> list[dict]:
    q = query.lower()
    for path in sorted((FIXTURES / "search").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = [k.lower() for k in data.get("match", [])]
        if keys and all(k in q for k in keys):
            return data.get("results", [])
    return []


def _mock_fetch(urls: list[str]) -> dict:
    results, errors = [], []
    index = {}
    for path in (FIXTURES / "fetch").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            index[r["url"]] = {**r, "recorded_at": data.get("recorded_at")}
    for u in urls:
        if u in index:
            results.append(index[u])
        else:
            errors.append({"url": u, "error": "not_in_mock_fixtures", "status": 404})
    return {"results": results, "errors": errors}


_client: TinyFishClient | None = None


def tinyfish() -> TinyFishClient:
    global _client
    if _client is None:
        _client = TinyFishClient()
    return _client


def reset_tinyfish(c: TinyFishClient | None = None) -> None:
    global _client
    _client = c


def elapsed(start: float) -> float:
    return round(time.monotonic() - start, 1)
