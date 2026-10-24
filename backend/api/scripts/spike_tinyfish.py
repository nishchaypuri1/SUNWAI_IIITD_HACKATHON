"""WP0 spike: one real call each to TinyFish Search, Fetch and Agent (run-sse) + GET /models per LLM provider.

    cd api && TINYFISH_API_KEY=... uv run python scripts/spike_tinyfish.py

Saves raw outputs under app/tinyfish/fixtures/live/ and prints a Markdown block to paste into docs/VERIFIED.md.
Uses only harmless pages (no portal is filled).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MOCK_MODE", "0")
os.environ["MOCK_MODE"] = "0"
os.environ["RECORD_FIXTURES"] = "1"

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.tinyfish.client import FIXTURES, TinyFishClient, TinyFishError  # noqa: E402

OUT = FIXTURES / "live"


async def main() -> None:
    s = get_settings()
    OUT.mkdir(parents=True, exist_ok=True)
    tf = TinyFishClient(s)
    report: list[str] = [f"## WP0 spike — {time.strftime('%Y-%m-%d %H:%M %Z')}", ""]

    # 1. Search
    for loc in ("IN", "US"):
        try:
            t0 = time.monotonic()
            res = await tf.search("Reserve Bank Integrated Ombudsman Scheme 2026", location=loc)
            (OUT / f"search_{loc}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
            report.append(f"- Search location={loc}: {len(res)} results in {time.monotonic()-t0:.1f}s; "
                          f"top: {res[0]['url'] if res else '-'}")
            break
        except TinyFishError as e:
            report.append(f"- Search location={loc}: {e.code} {e.message}")

    # 2. Fetch (raw response kept to record exact field names)
    url = "https://www.rbi.org.in/commonperson/english/scripts/FAQs.aspx?Id=3407"
    try:
        async with httpx.AsyncClient(timeout=150) as c:
            t0 = time.monotonic()
            r = await c.post(s.tinyfish_fetch_url, headers={"X-API-Key": s.tinyfish_api_key},
                             json={"urls": [url], "format": "markdown", "ttl": 0})
        raw = r.json()
        (OUT / "fetch_rbi_raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False))
        first = (raw.get("results") or [{}])[0]
        report.append(f"- Fetch HTTP {r.status_code} in {time.monotonic()-t0:.1f}s; top-level keys {sorted(raw)}; "
                      f"result keys {sorted(first)}; text chars {len(first.get('text') or '')}")
        text = first.get("text") or ""
        for needle in ("90 days", "whichever is later", "30 days", "July 1, 2026"):
            report.append(f"  - contains '{needle}': {needle in text}")
    except Exception as e:
        report.append(f"- Fetch failed: {type(e).__name__}: {e}")

    # 3. Agent run-sse on a harmless page
    events: list[dict] = []

    async def on_event(evt: dict) -> None:
        events.append(evt)
        print(evt.get("type"), (evt.get("purpose") or evt.get("status") or "")[:80])

    try:
        t0 = time.monotonic()
        complete = await tf.run_sse("https://scrapeme.live/shop", "Extract the first 2 product names and prices. Return JSON.",
                                    on_event=on_event, agent_config={"max_steps": 20},
                                    output_schema={"type": "object", "properties": {"products": {"type": "array", "items": {
                                        "type": "object", "properties": {"name": {"type": "string"},
                                                                         "price": {"type": "string"}}}}}})
        types = sorted({e.get("type") for e in events})
        report.append(f"- Agent run-sse: {len(events)} events {types} in {time.monotonic()-t0:.1f}s; "
                      f"COMPLETE status {complete.get('status')}; result {json.dumps(complete.get('result'))[:200]}")
        rid = complete.get("run_id")
        if rid:
            run = await tf.get_run(rid)
            (OUT / "get_run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))
            report.append(f"- GET /v1/runs/{{id}} keys: {sorted(run)}; video_url present: {bool(run.get('video_url'))}")
    except TinyFishError as e:
        report.append(f"- Agent run-sse failed: {e.code} {e.message}")

    # 4. LLM model ids
    for name, p in s.providers.items():
        if not p.api_key:
            report.append(f"- LLM {name}: no API key")
            continue
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"{p.base_url}/models", headers={"Authorization": f"Bearer {p.api_key}"})
            ids = [m.get("id") for m in r.json().get("data", [])]
            family = [i for i in ids if any(k in i for k in (name, "deepseek", "glm", "nemotron"))][:15]
            report.append(f"- LLM {name}: configured `{p.model}` listed={p.model in ids}; similar: {family}")
        except Exception as e:
            report.append(f"- LLM {name}: /models failed ({type(e).__name__})")

    print("\n".join(["", *report, ""]))


if __name__ == "__main__":
    asyncio.run(main())
