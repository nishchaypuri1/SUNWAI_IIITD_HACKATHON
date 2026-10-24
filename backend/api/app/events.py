"""EventBus: every event is written to the `events` table (its autoincrement id is the SSE id) and fanned
out to live SSE subscribers.

Global events (case_id=None) come from rule refreshes. Only `rule_changed` reaches case streams; the refresh
run's own progress is available from GET /api/runs/{run_id}.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from . import clock, db

log = logging.getLogger("sunwai.events")
GLOBAL_TYPES = {"rule_changed"}


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, case_id: str | None, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        at = clock.now_iso()
        evt_id = db.ex("INSERT INTO events(case_id, type, payload_json, at) VALUES(?,?,?,?)",
                       (case_id, type_, db.dumps(payload), at))
        evt = {"id": evt_id, "case_id": case_id, "type": type_, "at": at, "payload": payload}
        targets: list[asyncio.Queue] = []
        if case_id is None:
            if type_ in GLOBAL_TYPES:
                for qs in self._subs.values():
                    targets.extend(qs)
        else:
            targets.extend(self._subs.get(case_id, ()))
        for q in targets:
            self._deliver(q, evt)
        return evt

    def _deliver(self, q: asyncio.Queue, evt: dict) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        def put() -> None:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:  # slow client: it will catch up from the DB on reconnect
                log.warning("SSE queue full; dropping live event %s", evt["id"])

        if self._loop is not None and running is not self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(put)
        else:
            put()

    def subscribe(self, case_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subs[case_id].add(q)
        return q

    def unsubscribe(self, case_id: str, q: asyncio.Queue) -> None:
        self._subs.get(case_id, set()).discard(q)

    @staticmethod
    def since(case_id: str, last_id: int) -> list[dict[str, Any]]:
        rows = db.q("SELECT * FROM events WHERE (case_id=? OR (case_id IS NULL AND type='rule_changed')) AND id>? "
                    "ORDER BY id", (case_id, last_id))
        return [{"id": r["id"], "case_id": r["case_id"], "type": r["type"], "at": r["at"],
                 "payload": json.loads(r["payload_json"])} for r in rows]


def sse_format(evt: dict[str, Any]) -> str:
    data = json.dumps(evt, ensure_ascii=False, separators=(",", ":"))
    return f"id: {evt['id']}\nevent: {evt['type']}\ndata: {data}\n\n"


bus = EventBus()
