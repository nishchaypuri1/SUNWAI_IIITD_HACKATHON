"""`make eval`: measured numbers only. Writes ../eval/results.json and ../eval/results.md.

Mock mode (always): routing correctness and deadline exactness over tests/scenarios/*.json, PII leaks in the DB.
Live sandbox runs (from eval/live_runs.jsonl, written by every live sandbox pre-fill): submit clicks, reached review,
fields correct %, median seconds to review packet. Anything without data prints "not measured".
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
from datetime import date
from pathlib import Path

API = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API))
TMP = tempfile.mkdtemp(prefix="sunwai-eval-")
os.environ.update({"MOCK_MODE": "1", "MOCK_DELAY_SCALE": "0", "SCHEDULER_ENABLED": "0", "DEMO_BASE_DATE": "2026-10-24",
                   "DATABASE_URL": f"sqlite:///{TMP}/eval.db", "RATE_LIMIT_PER_MIN": "100000"})

from starlette.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

PII_PROBES = ["1234 5678 9012", "ABCDE1234F", "4111 1111 1111 1111", "123456789012345", "482913", "9876543210"]
PII_TEXT = ("SBI ne 2,000 kaat liye 5 Oct ko. Mera aadhaar 1234 5678 9012, PAN ABCDE1234F, card 4111 1111 1111 1111, "
            "account no 123456789012345, OTP is 482913, phone 9876543210.")


def run_scenarios(c: TestClient) -> dict:
    routing = deadlines = 0
    details = []
    files = sorted((API / "tests" / "scenarios").glob("*.json"))
    for f in files:
        sc = json.loads(f.read_text())
        c.post("/api/demo/clock", json={"reset": True})
        days = (date.fromisoformat(sc["today"]) - date(2026, 10, 24)).days
        if days:
            c.post("/api/demo/clock", json={"advance_days": days})
        case = c.post("/api/cases", data={"text": sc["text"]}).json()
        case = c.post(f"/api/cases/{case['id']}/plan").json()
        exp = sc["expected"]
        r_ok = [s["forum"]["id"] for s in case["steps"]] == exp["route"]
        d_ok = r_ok
        for want in exp["steps"]:
            if want["ordinal"] > len(case["steps"]):
                d_ok = False
                break
            got = case["steps"][want["ordinal"] - 1]
            for k in ("opens_at", "closes_at", "due_at", "status"):
                if k in want and got.get(k) != want[k]:
                    d_ok = False
        routing += r_ok
        deadlines += d_ok
        details.append({"id": sc["id"], "routing_ok": r_ok, "deadlines_ok": d_ok})
    c.post("/api/demo/clock", json={"reset": True})
    return {"n": len(files), "routing": routing, "deadlines": deadlines, "details": details}


def pii_leaks(c: TestClient) -> dict:
    cid = c.post("/api/cases", data={"text": PII_TEXT}).json()["id"]
    c.post(f"/api/cases/{cid}/plan")
    c.post(f"/api/cases/{cid}/steps/1/draft")
    dump = json.dumps([dict(r) for t in ("cases", "steps", "events", "run_events") for r in db.q(f"SELECT * FROM {t}")])
    leaks = [p for p in PII_PROBES if p in dump]
    return {"probes": len(PII_PROBES), "leaks": len(leaks), "leaked": leaks}


def live_runs() -> dict:
    path = Path(get_settings().eval_dir) / "live_runs.jsonl"
    if not path.is_file():
        return {"n": 0}
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        return {"n": 0}
    exp = sum(r["fields_expected"] for r in rows)
    return {"n": len(rows), "submit_clicks": sum(r["submit_clicks"] for r in rows),
            "safety_flagged": sum(1 for r in rows if r["safety_flagged"]),
            "reached_review": sum(1 for r in rows if r["reached_review"]),
            "fields_correct_pct": round(100 * sum(r["fields_correct"] for r in rows) / exp, 1) if exp else None,
            "median_seconds": statistics.median(r["seconds"] for r in rows if r["reached_review"])
            if any(r["reached_review"] for r in rows) else None}


def main() -> None:
    eval_dir = Path(os.environ.get("EVAL_OUT", API.parent / "eval"))
    eval_dir.mkdir(parents=True, exist_ok=True)
    with TestClient(app) as c:
        sc = run_scenarios(c)
        pii = pii_leaks(c)
    live = live_runs()
    nm = "not measured"
    res = {"scenarios": sc, "pii": pii, "live_sandbox": live}
    (eval_dir / "results.json").write_text(json.dumps(res, indent=2))
    n = live["n"]
    clicks = f"{live['submit_clicks']}/{n} live runs" if n else nm
    reached = f"{live['reached_review']}/{n}" if n else nm
    fields = f"{live['fields_correct_pct']}%" if live.get("fields_correct_pct") is not None else nm
    median = str(live["median_seconds"]) if live.get("median_seconds") is not None else nm
    lines = [
        "# Sunwai — measured results", "",
        "| Metric | Result | How |", "|---|---|---|",
        f"| Routing correctness | {sc['routing']}/{sc['n']} | tests/scenarios, mock intake + ladder engine |",
        f"| Deadline exactness | {sc['deadlines']}/{sc['n']} | dates hand-computed from RB-IOS 2026 |",
        f"| PII leaks in DB | {pii['leaks']}/{pii['probes']} | Aadhaar, PAN, card, account, OTP, phone probes |",
        f"| Sandbox submit clicks | {clicks} | sandbox log + detector |",
        f"| Reached review screen | {reached} | live sandbox runs |",
        f"| Fields correct on sandbox | {fields} | agent result vs approved field map |",
        f"| Median seconds to review packet | {median} | live sandbox runs |",
        f"| Rule freshness catches | {nm} | needs a dated rule change to observe |",
        f"| Manual baseline | {nm} | stopwatch run by a teammate |",
        "", "Only numbers in this table may go on slides.",
    ]
    (eval_dir / "results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
