"""Full demo path through the HTTP API in mock mode (create -> plan -> draft -> preview -> prefill -> submitted ->
clock +30 -> prepare-next), plus status checks, SSE replay and the evidence pack."""
import io
import json

from PIL import Image

from tests.conftest import wait_for_runs

PHONEPE_NEW = ("PhonePe se 20 Oct ko 1,499 rupaye do baar kaat liye. UTR 629384710562. Abhi tak bank ya PhonePe ko "
               "complaint nahi ki. Paise wapas chahiye.")


def create(c, text=PHONEPE_NEW, **kw):
    r = c.post("/api/cases", data={"text": text, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_health_and_reference_endpoints(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["mock_mode"] and h["tinyfish"] == "missing_key"
    assert set(h["models"]) == {"intake", "reason", "fast"}
    assert len(client.get("/api/demo/scenarios").json()["items"]) >= 5
    assert [f["id"] for f in client.get("/api/forums").json()["items"]] == [
        "company_grievance", "rbi_cms", "nch", "consumer_commission"]
    clock = client.get("/api/demo/clock").json()
    assert clock == {**clock, "today": "2026-10-24", "offset_days": 0, "simulated": False}


def test_rule_refreshed_from_recorded_official_text(client):
    rule = client.get("/api/rules/rbi_cms").json()
    assert rule["filing_window_days"] == 90 and rule["wait_days_before_escalation"] == 30
    assert rule["filing_window_counts_from"] == "later_of_wait_end_or_last_reply"
    assert rule["source_domain"] == "rbi.org.in" and rule["confidence"] == "high"
    assert "whichever is later" in rule["evidence_snippet"]
    assert len(rule["evidence_snippet"].split()) <= 26  # <= 25 words plus the ellipsis mark
    assert rule["superseded_value_note"]


def test_full_demo_path(client):
    case = create(client)
    cid = case["id"]
    assert case["state"] == "INTAKE_DONE" and case["steps"] == []
    assert case["disclaimer"].startswith("Sunwai helps you follow the complaint procedure")
    cj = case["case_json"]
    assert cj["counterparty"] == {"name": "PhonePe", "type": "payment_app"}
    assert cj["amount_inr"] == 1499 and cj["incident_date"] == "2026-10-20"
    assert cj["reference_numbers"] == ["629384710562"]

    case = client.post(f"/api/cases/{cid}/plan").json()
    assert case["state"] == "LADDER_READY"
    s1, s2 = case["steps"]
    assert (s1["forum"]["id"], s1["status"]) == ("company_grievance", "open")
    assert (s2["forum"]["id"], s2["status"], s2["opens_at"]) == ("rbi_cms", "locked", None)
    assert s2["rule"]["freshness"] in ("live", "cached") and s2["rule"]["source_url"]

    draft = client.post(f"/api/cases/{cid}/steps/1/draft").json()
    assert draft["word_count"] <= 250 and draft["safety"]["ok"] and "629384710562" in draft["body"]
    assert "your full name" in " ".join(draft["placeholders_to_fill"])

    prev = client.get(f"/api/cases/{cid}/steps/1/prefill/preview?portal=sandbox").json()
    fm = {f["label"]: f["value"] for f in prev["field_map"]}
    assert fm["Transaction date"] == "20/10/2026" and fm["Amount (₹)"] == "1499"
    assert fm["Transaction reference"] == "629384710562" and fm["Customer name"] is None
    assert prev["portal_url"] == "https://sandbox.example.test/sandbox/grievance"
    assert client.get(f"/api/cases/{cid}").json()["state"] == "AWAITING_APPROVAL"

    r = client.post(f"/api/cases/{cid}/steps/1/prefill", json={"portal": "sandbox"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "APPROVAL_REQUIRED"
    r = client.post(f"/api/cases/{cid}/steps/1/prefill", json={"approved": True, "portal": "sandbox"})
    assert r.status_code == 202
    run = wait_for_runs(client, r.json()["run_id"])
    assert run["status"] == "completed" and run["tinyfish_run_id"].startswith("tf_mock_")
    assert [e["tf_type"] for e in run["events"]][0] == "STARTED"
    assert "HEARTBEAT" not in [e["tf_type"] for e in run["events"]]

    case = client.get(f"/api/cases/{cid}").json()
    s1 = case["steps"][0]
    assert case["state"] == "REVIEW_READY" and s1["status"] == "review_ready"
    pk = s1["review_packet"]
    assert pk["reached_review_screen"] and pk["stopped_before_submit"] and not pk["safety_flagged"]
    assert {f["label"] for f in pk["fields"] if f["filled"]} >= {"Transaction date", "Amount (₹)"}

    # prepare-next is not allowed yet
    r = client.post(f"/api/cases/{cid}/steps/1/prepare-next")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ILLEGAL_TRANSITION"

    case = client.post(f"/api/cases/{cid}/steps/1/submitted",
                       json={"ack_number": "KDB-2026-1188", "submitted_at": "2026-10-24"}).json()
    s1, s2 = case["steps"]
    assert case["state"] == "WAITING"
    assert (s1["status"], s1["ack_number"], s1["due_at"]) == ("waiting", "KDB-2026-1188", "2026-11-23")
    assert (s2["opens_at"], s2["closes_at"], s2["days_until_open"]) == ("2026-11-23", "2027-02-21", 30)

    clock = client.post("/api/demo/clock", json={"advance_days": 30}).json()
    assert clock["simulated"] and clock["today"] == "2026-11-23"
    case = client.get(f"/api/cases/{cid}").json()
    assert case["state"] == "DUE" and [s["status"] for s in case["steps"]] == ["due", "open"]

    pack = client.post(f"/api/cases/{cid}/steps/1/prepare-next").json()
    assert pack["recommendation"] == "escalate" and pack["next_forum_id"] == "rbi_cms"
    assert pack["filing_deadline"] == "2027-02-21"
    assert "KDB-2026-1188" in pack["draft"]["body"] and "30 days" in pack["draft"]["body"]
    assert client.get(f"/api/cases/{cid}").json()["state"] == "ESCALATION_READY"

    # status check (G2 on the sandbox status page; S4 data)
    r = client.post(f"/api/cases/{cid}/steps/1/check-status", json={})
    assert r.status_code == 202
    wait_for_runs(client, r.json()["run_id"])
    chk = client.get(f"/api/cases/{cid}").json()["steps"][0]["status_checks"][0]
    assert chk["normalized_status"] == "in_progress" and chk["status_text"] == "Under review"

    # SSE replay contains the key moments in order
    from app.events import bus
    types = [e["type"] for e in bus.since(cid, 0)]
    for t in ("run_started", "agent_event", "review_ready", "run_completed", "step_due", "draft_ready",
              "status_checked"):
        assert t in types, t
    assert types.index("run_started") < types.index("review_ready")
    ids = [e["id"] for e in bus.since(cid, 0)]
    assert ids == sorted(ids)
    assert all(e["id"] > ids[3] for e in bus.since(cid, ids[3]))

    md = client.get(f"/api/cases/{cid}/evidence-pack")
    assert md.status_code == 200 and "KDB-2026-1188" in md.text and "not legal advice" in md.text
    assert "attachment" in md.headers["content-disposition"]
    assert client.get(f"/api/cases/{cid}/evidence-pack?format=pdf").status_code == 400

    summary = client.get("/api/cases").json()["items"][0]
    assert summary["id"] == cid and summary["next_deadline"] == "2027-02-21" and summary["current_step"] == 2

    case = client.post(f"/api/cases/{cid}/close", json={"reason": "resolved"}).json()
    assert case["state"] == "RESOLVED"
    assert client.post(f"/api/cases/{cid}/plan").status_code == 409


def test_answers_flow_and_validation(client):
    case = create(client, "Amazon has not refunded ₹2,349 for my returned order. The return was picked up on 3 October 2026.")
    cid = case["id"]
    assert "prior_contact.contacted_company" in case["missing_fields"]
    q = case["questions"][0]
    assert q["field"] == "prior_contact.contacted_company" and q["question_hi"] and q["input"] == "boolean"
    r = client.post(f"/api/cases/{cid}/answers", json={"answers": {"prior_contact.date": "2099-01-01"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = client.post(f"/api/cases/{cid}/answers", json={"answers": {"nope": 1}})
    assert r.status_code == 422
    case = client.post(f"/api/cases/{cid}/answers", json={"answers": {
        "prior_contact.contacted_company": True, "prior_contact.date": "2026-10-05",
        "prior_contact.got_reply": False}}).json()
    assert case["missing_fields"] == []
    case = client.post(f"/api/cases/{cid}/plan").json()
    assert [s["forum"]["id"] for s in case["steps"]] == ["company_grievance", "nch", "consumer_commission"]
    # answering after planning replans automatically
    case = client.post(f"/api/cases/{cid}/answers", json={"answers": {
        "prior_contact.got_reply": True, "prior_contact.reply_date": "2026-10-10",
        "prior_contact.satisfied_with_reply": True}}).json()
    assert [s["status"] for s in case["steps"]] == ["done", "skipped", "skipped"]


def test_contradiction_question(client):
    case = create(client, "I complained to SBI on 1 October 2026. The failed UPI debit of Rs 500 happened on 10 October 2026.")
    assert case["questions"][0]["field"] == "prior_contact.date"
    assert case["questions"][0]["question"].startswith("Please check this date")
    assert any("before the incident date" in w for w in case["warnings"])


def test_uploads(client):
    buf = io.BytesIO()
    Image.new("RGB", (2400, 1200), "white").save(buf, "PNG")
    r = client.post("/api/cases", data={"text": PHONEPE_NEW}, files=[("files", ("s.png", buf.getvalue(), "image/png"))])
    assert r.status_code == 201 and "screenshot attached" in r.json()["case_json"]["evidence_found"]
    r = client.post("/api/cases", data={"text": PHONEPE_NEW}, files=[("files", ("a.gif", b"GIF89a", "image/gif"))])
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_FILE"
    big = b"\xff\xd8" + b"0" * (5 * 1024 * 1024 + 10)
    r = client.post("/api/cases", data={"text": PHONEPE_NEW}, files=[("files", ("b.jpg", big, "image/jpeg"))])
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
    r = client.post("/api/cases", data={"text": "short"})
    assert r.status_code == 422 and r.json()["error"]["details"]["fields"][0]["field"] == "text"
    four = [("files", (f"{i}.png", buf.getvalue(), "image/png")) for i in range(4)]
    assert client.post("/api/cases", data={"text": PHONEPE_NEW}, files=four).status_code == 422


def test_errors_are_contract_shaped(client):
    for path in ("/api/cases/nope", "/api/runs/nope", "/api/rules/nope", "/api/does-not-exist"):
        r = client.get(path)
        assert r.status_code == 404 and set(r.json()["error"]) == {"code", "message", "details"}
    cid = create(client)["id"]
    assert client.get(f"/api/cases/{cid}/steps/1/prefill/preview").status_code == 404  # not planned yet
    client.post(f"/api/cases/{cid}/plan")
    r = client.post(f"/api/cases/{cid}/steps/2/prefill", json={"approved": True, "portal": "sandbox"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ILLEGAL_TRANSITION"
    r = client.post(f"/api/cases/{cid}/steps/1/submitted", json={"ack_number": "AB123", "submitted_at": "2026-10-24"})
    assert r.status_code == 409
    r = client.post(f"/api/cases/{cid}/steps/1/submitted", json={"ack_number": "A", "submitted_at": "x"})
    assert r.status_code == 422
    assert client.post(f"/api/cases/{cid}/steps/2/discover").status_code == 409
    assert client.post(f"/api/cases/{cid}/answers", content="not json",
                       headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/api/demo/clock", json={}).status_code == 422


def test_portal_busy(client, monkeypatch):
    from app.services import runs as runs_svc
    a = create(client)["id"]
    b = create(client)["id"]
    for cid in (a, b):
        client.post(f"/api/cases/{cid}/plan")
    monkeypatch.setattr(runs_svc, "portal_busy", lambda key: True)
    r = client.post(f"/api/cases/{b}/steps/1/prefill", json={"approved": True, "portal": "sandbox"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PORTAL_BUSY"


def test_live_portal_hand_off_on_otp_wall(client):
    case = create(client, "PhonePe ne 1 Oct ko 1,499 do baar kaat liye, bank ko 2 Oct ko complaint ki, koi jawab nahi.")
    cid = case["id"]
    client.post(f"/api/cases/{cid}/plan")
    client.post("/api/demo/clock", json={"advance_days": 9})   # 2 Nov: RBI step is open
    assert client.get(f"/api/cases/{cid}").json()["steps"][1]["status"] == "open"
    prev = client.get(f"/api/cases/{cid}/steps/2/prefill/preview?portal=live").json()
    assert prev["portal_url"] == "https://cms.rbi.org.in"
    r = client.post(f"/api/cases/{cid}/steps/2/prefill", json={"approved": True, "portal": "live"})
    run = wait_for_runs(client, r.json()["run_id"])
    assert run["status"] == "blocked"
    case = client.get(f"/api/cases/{cid}").json()
    s2 = case["steps"][1]
    assert case["state"] == "BLOCKED" and s2["status"] == "blocked" and s2["review_packet"]["blocker"] == "otp"
    # the user files by hand and reports the acknowledgement
    case = client.post(f"/api/cases/{cid}/steps/2/submitted",
                       json={"ack_number": "CMS/2026/000123", "submitted_at": "2026-11-02"}).json()
    assert case["steps"][1]["status"] == "waiting" and case["steps"][1]["ack_number"] == "CMS/2026/000123"


def test_safety_flag_when_sandbox_logs_submit(client, monkeypatch):
    from app import repo
    cid = create(client)["id"]
    client.post(f"/api/cases/{cid}/plan")
    monkeypatch.setattr(repo, "sandbox_submit_clicks", lambda *a: 1)
    r = client.post(f"/api/cases/{cid}/steps/1/prefill", json={"approved": True, "portal": "sandbox"})
    run = wait_for_runs(client, r.json()["run_id"])
    assert run["status"] == "safety_flagged"
    case = client.get(f"/api/cases/{cid}").json()
    assert case["steps"][0]["status"] == "blocked"
    assert case["steps"][0]["review_packet"]["safety_flagged"] is True
    assert case["steps"][0]["review_packet"]["stopped_before_submit"] is False
    from app.events import bus
    assert "safety_flagged" in [e["type"] for e in bus.since(cid, 0)]


def test_safety_flag_when_agent_clicks_submit(client, monkeypatch, tmp_path):
    import shutil

    from app.tinyfish import client as tfc
    fx = tmp_path / "fx"
    shutil.copytree(tfc.FIXTURES, fx)
    text = (fx / "sse" / "fill_sandbox.sse").read_text().replace(
        "Review screen reached. Stopping before submit as instructed", "Clicking the Submit button")
    (fx / "sse" / "fill_sandbox.sse").write_text(text)
    monkeypatch.setattr(tfc, "FIXTURES", fx)
    cid = create(client)["id"]
    client.post(f"/api/cases/{cid}/plan")
    r = client.post(f"/api/cases/{cid}/steps/1/prefill", json={"approved": True, "portal": "sandbox"})
    assert wait_for_runs(client, r.json()["run_id"])["status"] == "safety_flagged"


def test_cancel_run(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "mock_delay_scale", 1.0)
    cid = create(client)["id"]
    client.post(f"/api/cases/{cid}/plan")
    rid = client.post(f"/api/cases/{cid}/steps/1/prefill", json={"approved": True, "portal": "sandbox"}).json()["run_id"]
    assert client.post(f"/api/runs/{rid}/cancel").json() == {"ok": True}
    run = wait_for_runs(client, rid)
    assert run["status"] == "cancelled"
    assert client.get(f"/api/cases/{cid}").json()["steps"][0]["status"] == "open"
    assert client.post(f"/api/runs/{rid}/cancel").json() == {"ok": True}  # idempotent


def test_discovery_records_route(client):
    cid = create(client)["id"]
    client.post(f"/api/cases/{cid}/plan")
    r = client.post(f"/api/cases/{cid}/steps/1/discover")
    assert r.status_code == 202
    wait_for_runs(client, r.json()["run_id"])
    step = client.get(f"/api/cases/{cid}").json()["steps"][0]
    route = step["grievance_route"]
    assert route["grievance_form_url"] == "https://grievance.phonepe.com/" and route["found_via"] == "mock"
    assert route["grievance_email"] is None and len(route["evidence_quote"].split()) <= 20
    assert step["forum"]["filing_url"] == "https://grievance.phonepe.com/"


def test_draft_edit_is_rechecked(client):
    cid = create(client)["id"]
    client.post(f"/api/cases/{cid}/plan")
    d = client.put(f"/api/cases/{cid}/steps/1/draft",
                   json={"subject": "Refund", "body": "I will sue you. My aadhaar is 1234 5678 9012."}).json()
    assert d["edited_by_user"] and not d["safety"]["ok"]
    assert "1234 5678 9012" not in d["body"]
    assert {i["type"] for i in d["safety"]["issues"]} >= {"threat", "pii"}


def test_sandbox_endpoints(client):
    assert client.post("/api/sandbox/attempts", json={"session_id": "run_x", "kind": "review_reached"}).json()["ok"]
    client.post("/api/sandbox/attempts", json={"session_id": "run_x", "kind": "form_opened"})
    s = client.get("/api/sandbox/attempts").json()
    assert s["review_reached"] == 1 and s["submit_clicked"] == 0 and len(s["items"]) == 2
    assert client.post("/api/sandbox/attempts", json={"session_id": "x", "kind": "bad"}).status_code == 422
    assert client.delete("/api/sandbox/attempts").json()["ok"]
    assert client.get("/api/sandbox/attempts").json()["items"] == []
    st = client.get("/api/sandbox/status/KDB-RP-1").json()
    assert st["status_text"] == "Replied" and st["last_updated"] == "2026-10-23"
    assert client.get("/api/sandbox/status/KDB-1").json()["status_text"] == "Under review"


def test_status_reply_unlocks_escalation(client):
    case = create(client, "PhonePe ne 1 Oct ko 1,499 do baar kaat liye, bank ko 2 Oct ko complaint ki, koi jawab nahi. "
                          "Complaint number PP-RJ-20261002.")
    cid = case["id"]
    client.post(f"/api/cases/{cid}/plan")
    r = client.post(f"/api/cases/{cid}/steps/1/check-status", json={"portal": "sandbox"})
    wait_for_runs(client, r.json()["run_id"])
    case = client.get(f"/api/cases/{cid}").json()
    assert case["steps"][0]["status_checks"][0]["normalized_status"] == "rejected"
    assert case["steps"][1]["status"] == "open"
    pack = client.post(f"/api/cases/{cid}/steps/1/prepare-next").json()
    assert pack["recommendation"] == "escalate"


def test_no_raw_pii_in_database(client, fresh_db):
    text = ("SBI ne 2,000 kaat liye 5 Oct ko. Mera aadhaar 1234 5678 9012, PAN ABCDE1234F, card 4111 1111 1111 1111, "
            "account no 123456789012345, OTP is 482913, phone 9876543210.")
    cid = create(client, text)["id"]
    client.post(f"/api/cases/{cid}/plan")
    client.post(f"/api/cases/{cid}/steps/1/draft")
    dump = (fresh_db / "test.db").read_bytes().decode("utf-8", "ignore")
    from app import db
    rows = json.dumps([dict(r) for r in db.q("SELECT * FROM cases")] + [dict(r) for r in db.q("SELECT * FROM steps")]
                      + [dict(r) for r in db.q("SELECT * FROM events")])
    for secret in ("1234 5678 9012", "ABCDE1234F", "4111 1111 1111 1111", "123456789012345", "482913", "9876543210"):
        assert secret not in rows, secret
        assert secret not in dump, secret


def test_openapi_covers_contract(client):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    expected = [
        ("get", "/api/health"), ("get", "/api/demo/scenarios"), ("get", "/api/demo/clock"), ("post", "/api/demo/clock"),
        ("get", "/api/forums"), ("get", "/api/cases"), ("post", "/api/cases"), ("post", "/api/cases/{case_id}/answers"),
        ("post", "/api/cases/{case_id}/plan"), ("get", "/api/cases/{case_id}"),
        ("post", "/api/cases/{case_id}/steps/{n}/discover"), ("post", "/api/cases/{case_id}/steps/{n}/draft"),
        ("put", "/api/cases/{case_id}/steps/{n}/draft"), ("get", "/api/cases/{case_id}/steps/{n}/prefill/preview"),
        ("post", "/api/cases/{case_id}/steps/{n}/prefill"), ("get", "/api/runs/{run_id}"),
        ("post", "/api/runs/{run_id}/cancel"), ("post", "/api/cases/{case_id}/steps/{n}/submitted"),
        ("post", "/api/cases/{case_id}/steps/{n}/check-status"), ("post", "/api/cases/{case_id}/steps/{n}/prepare-next"),
        ("post", "/api/cases/{case_id}/close"), ("get", "/api/cases/{case_id}/events"), ("get", "/api/rules/{forum_id}"),
        ("post", "/api/rules/{forum_id}/refresh"), ("get", "/api/cases/{case_id}/evidence-pack"),
        ("get", "/api/debug/llm-stats"), ("post", "/api/sandbox/attempts"), ("get", "/api/sandbox/attempts"),
        ("delete", "/api/sandbox/attempts"), ("get", "/api/sandbox/status/{complaint_number}"),
    ]
    for method, path in expected:
        assert method in paths.get(path, {}), (method, path)
    assert len(expected) == 30
    for name in ("Case", "Step", "Draft", "ReviewPacket", "Rule", "EscalationPack", "PrefillPreview", "Health"):
        assert name in spec["components"]["schemas"]
    assert client.get("/docs").status_code == 200


def test_rule_refresh_endpoint(client):
    r = client.post("/api/rules/rbi_cms/refresh")
    assert r.status_code == 202
    run = wait_for_runs(client, r.json()["run_id"])
    assert run["status"] == "completed" and run["kind"] == "rule_refresh"
    assert any("Verified 3 of 3" in e["message"] for e in run["events"])
    assert client.get("/api/debug/llm-stats").json()["calls"] >= 1
