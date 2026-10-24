"""Live-mode wiring (MOCK_MODE=0) against fake TinyFish and fake LLM servers: proves the real code paths
(rule refresh with quote verification, P-prompts through the gateway, run-sse relay, get_run, review packet,
eval log) work end to end without network."""
import json
import re

import httpx
import pytest

from tests.conftest import wait_for_runs

RBI_TEXT = ("Reserve Bank - Integrated Ombudsman Scheme, 2026\n\nIt comes into force with effect from July 1, 2026.\n\n"
            "A complaint can be filed before the RBI Ombudsman if the complainant has not received any reply within "
            "30 days or if the complainant is not satisfied with the reply.\n\nThe complaint must be made to the RBI "
            "Ombudsman within 90 days from the date on which the above timeline expires or the date of the last "
            "communication from the concerned Regulated Entity, whichever is later.")
WINDOW_Q = ("The complaint must be made to the RBI Ombudsman within 90 days from the date on which the above timeline "
            "expires or the date of the last communication from the concerned Regulated Entity, whichever is later.")
WAIT_Q = "has not received any reply within 30 days"

SENT: dict[str, list] = {"agent": [], "llm": []}


def llm_handler(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content)
    SENT["llm"].append(body)
    system = body["messages"][0]["content"]
    user = body["messages"][-1]["content"]
    if system.startswith("You extract a structured"):
        from datetime import date

        from app.llm.mock_brain import extract_case
        text = re.search(r"<user_text>\n(.*)\n</user_text>", user, re.S).group(1)
        out = extract_case(text, date(2026, 10, 24))
    elif system.startswith("You read OFFICIAL"):
        out = {"scheme_name": "Reserve Bank - Integrated Ombudsman Scheme, 2026", "effective_from": "2026-07-01",
               "wait_days_before_escalation": 30, "filing_window_days": 90,
               "filing_window_counts_from": "later_of_wait_end_or_last_reply",
               "evidence": {"wait_days_before_escalation": WAIT_Q, "filing_window_days": WINDOW_Q,
                            "filing_window_counts_from": "within 90 days … whichever is later",
                            "effective_from": "with effect from July 1, 2026"}, "confidence": "high"}
    elif system.startswith("You explain an escalation plan"):
        out = {"steps": [{"ordinal": 1, "why": "Complain to the app first, then wait 99 days.", "why_hi": "x"}],
               "order_check": []}
    elif system.startswith("You draft"):
        out = {"subject": "Double debit of Rs 1,499", "body": "Dear Sir/Madam,\nPlease refund.\n[please fill: your full name]",
               "attachments_to_mention": ["Screenshot"]}
    elif system.startswith("You map a complaint case"):
        out = {"field_map": [{"label": "Amount (₹)", "value": "1499", "source": "case_json.amount_inr"},
                             {"label": "Customer name", "value": "123456789012", "source": "invented"}], "warnings": []}
    elif system.startswith("You are a safety checker"):
        out = {"ok": True, "issues": []}
    else:
        out = {}
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}]})


def tf_handler(req: httpx.Request) -> httpx.Response:
    host, path = req.url.host, req.url.path
    if host == "api.search.tinyfish.ai":
        return httpx.Response(200, json={"query": "q", "results": [
            {"position": 1, "title": "RB-IOS 2026", "url": "https://www.rbi.org.in/faq", "snippet": "", "site_name": "rbi"}]})
    if host == "api.fetch.tinyfish.ai":
        return httpx.Response(200, json={"results": [{"url": "https://www.rbi.org.in/faq", "title": "RB-IOS 2026",
                                                      "text": RBI_TEXT}], "errors": []})
    if path == "/v1/automation/run-sse":
        body = json.loads(req.content)
        SENT["agent"].append(body)
        result = {"reached_review_screen": True, "page_url": body["url"] + "#review",
                  "fields_filled": [{"label": "Amount (₹)", "value": "1499"}], "fields_missing": ["Customer name"],
                  "blocker": "none", "final_submit_clicked": False, "notes": "Stopped at review."}
        events = [
            {"type": "STARTED", "run_id": "tf_live_1", "timestamp": "2026-10-24T07:00:00Z"},
            {"type": "STREAMING_URL", "run_id": "tf_live_1", "streaming_url": "https://stream.tinyfish/x", "timestamp": "t"},
            {"type": "PROGRESS", "run_id": "tf_live_1", "purpose": "Typing the amount", "timestamp": "t"},
            {"type": "PROGRESS", "run_id": "tf_live_1", "purpose": "Clicking Review", "timestamp": "t"},
            {"type": "HEARTBEAT", "timestamp": "t"},
            {"type": "COMPLETE", "run_id": "tf_live_1", "status": "COMPLETED", "result": result, "timestamp": "t"},
        ]
        content = "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})
    if path == "/v1/runs/tf_live_1":
        return httpx.Response(200, json={"run_id": "tf_live_1", "status": "COMPLETED", "video_url": "https://v/x.mp4",
                                         "steps": [{"action": "type 1499 into Amount", "screenshot": "https://s/1.png"},
                                                   {"action": "click Review"}]})
    return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": path}})


@pytest.fixture()
def live_client(fresh_db, monkeypatch):
    from starlette.testclient import TestClient

    from app.config import get_settings, reset_settings_cache
    from app.llm import gateway as gw
    from app.tinyfish import client as tfc

    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("TINYFISH_API_KEY", "tf_test")
    for p in ("DEEPSEEK", "GLM", "NEMOTRON"):
        monkeypatch.setenv(f"{p}_API_KEY", "k")
        monkeypatch.setenv(f"{p}_RPS", "1000")
    reset_settings_cache()
    s = get_settings()
    gw.reset_gateway(gw.Gateway(s, transport=httpx.MockTransport(llm_handler)))
    tfc.reset_tinyfish(tfc.TinyFishClient(s, transport=httpx.MockTransport(tf_handler)))
    SENT["agent"].clear()
    SENT["llm"].clear()
    from app.main import app
    with TestClient(app) as c:
        wait_for_runs(c)
        yield c
    reset_settings_cache()


def test_live_flow_with_fake_servers(live_client, fresh_db):
    c = live_client
    rule = c.get("/api/rules/rbi_cms").json()
    assert rule["confidence"] == "high" and rule["source_domain"] == "rbi.org.in" and rule["freshness"] == "live"
    assert rule["evidence"]["filing_window_counts_from"] == "within 90 days … whichever is later"

    case = c.post("/api/cases", data={"text": "PhonePe se 20 Oct ko 1,499 rupaye do baar kaat liye. "
                                              "Abhi tak complaint nahi ki."}).json()
    cid = case["id"]
    case = c.post(f"/api/cases/{cid}/plan").json()
    s1 = case["steps"][0]
    assert "99" not in s1["why"]          # LLM sentence with an invented number was rejected
    assert s1["status"] == "open" and case["steps"][1]["needs_verification"] is False

    prev = c.get(f"/api/cases/{cid}/steps/1/prefill/preview?portal=sandbox").json()
    fm = {f["label"]: f["value"] for f in prev["field_map"]}
    assert fm["Amount (₹)"] == "1499"
    assert fm["Customer name"] == "XXXX XXXX 9012"   # anything not a known reference is scrubbed

    run_id = c.post(f"/api/cases/{cid}/steps/1/prefill", json={"approved": True, "portal": "sandbox"}).json()["run_id"]
    run = wait_for_runs(c, run_id)
    assert run["status"] == "completed" and run["tinyfish_run_id"] == "tf_live_1"
    assert run["streaming_url"] == "https://stream.tinyfish/x" and run["video_url"] == "https://v/x.mp4"

    body = SENT["agent"][-1]
    assert body["url"] == f"https://sandbox.example.test/sandbox/grievance?session={run_id}"
    assert body["agent_config"] == {"max_steps": 60, "max_duration_seconds": 240}
    assert body["capture_config"] == {"screenshots": True, "recording": True}
    assert body["output_schema"]["properties"]["final_submit_clicked"]["type"] == "boolean"
    assert body["goal"].startswith("This is a dry run.") and "NEVER click" in body["goal"]
    assert "123456789012" not in body["goal"]

    step = c.get(f"/api/cases/{cid}").json()["steps"][0]
    pk = step["review_packet"]
    assert step["status"] == "review_ready" and pk["stopped_before_submit"] and pk["screenshots"] == ["https://s/1.png"]

    from app.events import bus
    types = [e["type"] for e in bus.since(cid, 0)]
    assert "streaming_url" in types and types.count("agent_event") >= 4

    rows = [json.loads(x) for x in (fresh_db / "eval" / "live_runs.jsonl").read_text().splitlines()]
    assert rows[-1]["submit_clicks"] == 0 and rows[-1]["reached_review"] and rows[-1]["fields_correct"] == 1

    # no secret ever reaches the LLM: the P1 call carried masked text only
    assert all("9876543210" not in json.dumps(b) for b in SENT["llm"])
    h = c.get("/api/health").json()
    assert h["mock_mode"] is False and h["tinyfish"] == "ok"
