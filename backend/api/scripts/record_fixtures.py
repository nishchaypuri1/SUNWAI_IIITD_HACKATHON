"""Run the demo path LIVE and record every LLM output and TinyFish SSE stream as fixtures.

    cd api && RECORD_FIXTURES=1 MOCK_MODE=0 uv run python scripts/record_fixtures.py

LLM outputs land in app/llm/fixtures/{prompt}/{sha}.json (used automatically by MOCK_MODE=1 when the same
scrubbed input comes in). Raw agent streams land in app/tinyfish/fixtures/live/{run_id}.sse; copy a good
sandbox run over app/tinyfish/fixtures/sse/fill_sandbox.sse if you want the mock replay to use it.
Requires SANDBOX_PUBLIC_URL to point at the deployed sandbox page.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MOCK_MODE"] = "0"
os.environ["RECORD_FIXTURES"] = "1"
os.environ.setdefault("SCHEDULER_ENABLED", "0")

from starlette.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import scenarios  # noqa: E402


def wait(c, run_id, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/runs/{run_id}").json()
        if r["status"] not in ("queued", "running"):
            return r
        time.sleep(1)
    raise SystemExit(f"run {run_id} timed out")


def main() -> None:
    with TestClient(app) as c:
        rid = c.post("/api/rules/rbi_cms/refresh").json()["run_id"]
        print("rule refresh:", wait(c, rid)["status"])
        for sc in scenarios():
            case = c.post("/api/cases", data={"text": sc["text"], "language": sc["language"]}).json()
            case = c.post(f"/api/cases/{case['id']}/plan").json()
            print(sc["id"], case["state"], [s["status"] for s in case["steps"]])
            for s in case["steps"]:
                if s["status"] == "open" and s["forum"]["id"] != "consumer_commission":
                    c.post(f"/api/cases/{case['id']}/steps/{s['ordinal']}/draft")
        demo = scenarios()[0]
        case = c.post("/api/cases", data={"text": demo["text"], "language": demo["language"]}).json()
        c.post(f"/api/cases/{case['id']}/plan")
        c.get(f"/api/cases/{case['id']}/steps/1/prefill/preview?portal=sandbox")
        rid = c.post(f"/api/cases/{case['id']}/steps/1/prefill", json={"approved": True, "portal": "sandbox"}).json()
        print("sandbox prefill:", json.dumps(wait(c, rid["run_id"]))[:300])


if __name__ == "__main__":
    main()
