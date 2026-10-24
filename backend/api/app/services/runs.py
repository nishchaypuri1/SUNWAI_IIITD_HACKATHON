"""Shared helpers for background agent runs: task registry, per-portal lock, TinyFish->SSE event relay."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from .. import clock, repo
from ..errors import ApiError
from ..events import bus

log = logging.getLogger("sunwai.runs")

_tasks: dict[str, asyncio.Task] = {}
_portal_locks: dict[str, str] = {}      # portal_key -> run_id (in-process guard, DB is the source of truth)


def portal_key(portal_mode: str, url: str) -> str:
    host = urlparse(url).netloc or url
    return f"{portal_mode}:{host}"


def acquire_portal(key: str, run_id: str) -> None:
    if key in _portal_locks and _portal_locks[key] != run_id:
        raise ApiError(409, "PORTAL_BUSY", "Another agent run is already active on this portal. Please wait.")
    active = repo.active_run_on_portal(key)
    if active and active["id"] != run_id:
        raise ApiError(409, "PORTAL_BUSY", "Another agent run is already active on this portal. Please wait.")
    _portal_locks[key] = run_id


def release_portal(key: str | None, run_id: str) -> None:
    if key and _portal_locks.get(key) == run_id:
        _portal_locks.pop(key, None)


def portal_busy(key: str) -> bool:
    return key in _portal_locks or repo.active_run_on_portal(key) is not None


def start(run_id: str, coro: Awaitable[Any]) -> None:
    task = asyncio.get_running_loop().create_task(coro, name=run_id)
    _tasks[run_id] = task

    def done(t: asyncio.Task) -> None:
        _tasks.pop(run_id, None)
        if not t.cancelled() and t.exception() is not None:
            log.error("Run %s crashed: %r", run_id, t.exception())

    task.add_done_callback(done)


def cancel_task(run_id: str) -> bool:
    t = _tasks.get(run_id)
    if t and not t.done():
        t.cancel()
        return True
    return False


async def wait_all(timeout: float = 5.0) -> None:
    """Used by tests and shutdown."""
    pending = [t for t in _tasks.values() if not t.done()]
    if pending:
        await asyncio.wait(pending, timeout=timeout)


def message_for(evt: dict, host: str) -> str | None:
    t = evt.get("type")
    if t == "STARTED":
        return f"Agent started on {host}"
    if t == "PROGRESS":
        return str(evt.get("purpose") or "Working…")
    if t == "TF_API_RESULT":
        res = evt.get("result") or []
        return f"TinyFish {evt.get('tinyfish_api', 'api')} returned {len(res) if isinstance(res, list) else 1} result(s)"
    if t == "STREAMING_URL":
        return "Live browser view available"
    if t == "COMPLETE":
        return f"Agent finished ({evt.get('status', 'UNKNOWN')})"
    if t == "HEARTBEAT":
        return None
    return f"{t}: event received"


class Relay:
    """Turns TinyFish SSE events into our `agent_event` / `streaming_url` events and stores raw events."""

    def __init__(self, run_id: str, case_id: str | None, url: str) -> None:
        self.run_id = run_id
        self.case_id = case_id
        self.host = urlparse(url).netloc or url
        self.seq = 0
        self.raw_count = 0
        self.messages: list[str] = []

    async def __call__(self, evt: dict) -> None:
        self.raw_count += 1
        t = str(evt.get("type") or "UNKNOWN")
        if t == "STARTED" and evt.get("run_id"):
            repo.update_run(self.run_id, tinyfish_run_id=evt["run_id"], status="running")
        if t == "STREAMING_URL" and evt.get("streaming_url"):
            repo.update_run(self.run_id, streaming_url=evt["streaming_url"])
            bus.publish(self.case_id, "streaming_url", {"run_id": self.run_id, "streaming_url": evt["streaming_url"]})
        msg = message_for(evt, self.host)
        if msg is None:
            return
        if t == "PROGRESS":
            self.messages.append(msg)
        self.seq += 1
        raw = {k: v for k, v in evt.items() if k != "result"} if t == "COMPLETE" else evt
        repo.add_run_event(self.run_id, self.seq, t, msg, raw)
        repo.update_run(self.run_id, raw_events_count=self.raw_count)
        bus.publish(self.case_id, "agent_event", {"run_id": self.run_id, "seq": self.seq, "tf_type": t,
                                                  "message": msg})

    async def note(self, message: str, tf_type: str = "PROGRESS") -> None:
        """Our own progress line (e.g. 'Searching official sources…') on the same feed."""
        self.seq += 1
        repo.add_run_event(self.run_id, self.seq, tf_type, message, None)
        bus.publish(self.case_id, "agent_event", {"run_id": self.run_id, "seq": self.seq, "tf_type": tf_type,
                                                  "message": message})


def finish(run_id: str, status: str, *, error: dict | None = None, **fields: Any) -> None:
    repo.update_run(run_id, status=status, ended_at=clock.now_iso(), error_json=error, **fields)


ERROR_COPY: dict[str, tuple[str, bool]] = {
    "MISSING_API_KEY": ("TinyFish API key is missing. Set TINYFISH_API_KEY or run with MOCK_MODE=1.", False),
    "INVALID_API_KEY": ("TinyFish API key is invalid. Check TINYFISH_API_KEY or run with MOCK_MODE=1.", False),
    "UNAUTHORIZED": ("TinyFish rejected the API key. Check TINYFISH_API_KEY.", False),
    "INSUFFICIENT_CREDITS": ("TinyFish credits are exhausted. Top up, or switch to mock mode for the demo.", False),
    "FREE_ALLOWANCE_EXHAUSTED": ("TinyFish daily allowance is used up. Switch to mock mode for the demo.", False),
    "DAILY_LIMIT_EXCEEDED": ("TinyFish daily limit reached. Switch to mock mode for the demo.", False),
    "RATE_LIMIT_EXCEEDED": ("TinyFish is rate-limiting us. Please retry in a minute.", True),
    "SERVICE_BUSY": ("TinyFish is busy right now. Please retry.", True),
    "BACKEND_UNAVAILABLE": ("Cannot reach TinyFish right now. Please retry.", True),
    "TIMEOUT": ("The agent run timed out. Please retry.", True),
    "MAX_STEPS_EXCEEDED": ("The agent ran out of steps before reaching the review screen. Please retry.", True),
    "TASK_FAILED": ("The agent could not complete the form. You can retry or fill it by hand.", True),
    "SITE_BLOCKED": ("The portal blocked the automated browser. Please continue by hand.", False),
    "CONTENT_POLICY_VIOLATION": ("TinyFish refused this task.", False),
}


def tinyfish_error_payload(code: str, fallback: str) -> dict:
    msg, retry = ERROR_COPY.get(code, (fallback, True))
    our_code = "TINYFISH_CONFIG" if code in ("MISSING_API_KEY", "INVALID_API_KEY", "UNAUTHORIZED") else (
        "TINYFISH_UNAVAILABLE" if code in ("SERVICE_BUSY", "BACKEND_UNAVAILABLE") else code)
    return {"code": our_code, "message": msg, "retryable": retry}


Callback = Callable[[], Awaitable[None]]
