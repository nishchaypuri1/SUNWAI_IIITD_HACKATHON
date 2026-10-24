"""Tolerant Server-Sent Events decoder for TinyFish agent streams.

Accumulates `data:` lines until a blank line, honours `event:` / `id:`, ignores comments, skips undecodable
payloads, and also copes with servers that send one JSON object per `data:` line without blank separators.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Iterator

log = logging.getLogger("sunwai.tinyfish.sse")


class SSEDecoder:
    def __init__(self) -> None:
        self._data: list[str] = []
        self._event: str | None = None
        self._id: str | None = None

    def feed(self, line: str) -> list[dict]:
        line = line.rstrip("\r\n")
        if line == "":
            return self._dispatch()
        if line.startswith(":"):
            return []
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        out: list[dict] = []
        if field == "data":
            # A new complete JSON object while one is pending and no blank line came: flush the pending one.
            if self._data and _is_json_obj("\n".join(self._data)) and _is_json_obj(value):
                out.extend(self._dispatch())
            self._data.append(value)
        elif field == "event":
            self._event = value
        elif field == "id":
            self._id = value
        return out

    def flush(self) -> list[dict]:
        return self._dispatch()

    def _dispatch(self) -> list[dict]:
        if not self._data:
            self._event = None
            return []
        raw = "\n".join(self._data)
        event, self._data, self._event = self._event, [], None
        out: list[dict] = []
        try:
            obj = json.loads(raw)
            objs = [obj]
        except json.JSONDecodeError:
            objs = []
            for part in raw.split("\n"):
                try:
                    objs.append(json.loads(part))
                except json.JSONDecodeError:
                    log.warning("Skipping undecodable SSE payload (%d chars)", len(part))
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            if "type" not in obj and event:
                obj["type"] = event
            out.append(obj)
        return out


def _is_json_obj(s: str) -> bool:
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return False
    try:
        return isinstance(json.loads(s), dict)
    except json.JSONDecodeError:
        return False


def parse_lines(lines: Iterable[str]) -> Iterator[dict]:
    dec = SSEDecoder()
    for line in lines:
        yield from dec.feed(line)
    yield from dec.flush()
