"""In-process scheduler (asyncio, no Redis/APScheduler needed):
- due-date sweep every 10 minutes (also in mock mode)
- rule refresh when the 24 h TTL expires (network; mock mode replays the recorded fetch once)
- daily status checks for waiting steps (live mode only, one run per portal)
"""
from __future__ import annotations

import asyncio
import logging
import time

from .. import repo
from ..config import get_settings
from ..core import states
from ..services import planning, rules, runs, tracking

log = logging.getLogger("sunwai.scheduler")

SWEEP_EVERY = 600
RULES_EVERY = 3600
STATUS_EVERY = 86400


async def _status_checks() -> None:
    for case in repo.list_cases():
        if case["state"] in states.TERMINAL_CASE_STATES:
            continue
        for step in repo.get_steps(case["id"]):
            if step["status"] != "waiting" or not step.get("ack_number"):
                continue
            try:
                await tracking.start_status_check(case["id"], step["ordinal"], step.get("last_portal_mode"))
            except Exception as e:  # portal busy / no status page: skip quietly
                log.info("Skipped status check %s/%s: %s", case["id"], step["ordinal"], getattr(e, "message", e))


async def loop() -> None:
    s = get_settings()
    last = {"sweep": time.monotonic(), "rules": 0.0, "status": time.monotonic()}
    while True:
        try:
            now = time.monotonic()
            if now - last["sweep"] >= SWEEP_EVERY:
                planning.sweep()
                last["sweep"] = now
            if now - last["rules"] >= RULES_EVERY:
                last["rules"] = now
                if rules.needs_refresh("rbi_cms") and (s.mock_mode or s.tinyfish_api_key):
                    await rules.refresh_now("rbi_cms")
            if not s.mock_mode and now - last["status"] >= STATUS_EVERY:
                last["status"] = now
                await _status_checks()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler tick failed")
        await asyncio.sleep(30)


_task: asyncio.Task | None = None


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(loop(), name="scheduler")


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        _task = None
    await runs.wait_all(2)
