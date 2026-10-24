"""Submitted (E18), status checks (E19, G2), and the deterministic sandbox status page data (S4)."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from .. import clock, repo
from ..config import get_settings
from ..core import states
from ..errors import bad_request, illegal, validation_error
from ..events import bus
from ..llm.gateway import gateway
from ..tinyfish import goals
from ..tinyfish.client import TinyFishError, tinyfish
from . import planning, runs

log = logging.getLogger("sunwai.tracking")


# ------------------------------------------------------------ E18
async def mark_submitted(case_id: str, ordinal: int, ack_number: str, submitted_at: str) -> dict:
    case = repo.get_case(case_id)
    if case["state"] in states.TERMINAL_CASE_STATES:
        raise illegal("This case is closed.")
    step = repo.get_step(case_id, ordinal)
    states.assert_can_submit(step)
    d = clock.parse_date(submitted_at)
    if d is None:
        raise validation_error([{"field": "submitted_at", "message": "Expected YYYY-MM-DD."}])
    if d > clock.today():
        raise validation_error([{"field": "submitted_at", "message": "Date cannot be in the future."}])
    ack = ack_number.strip()
    if not (3 <= len(ack) <= 64):
        raise validation_error([{"field": "ack_number", "message": "Must be 3-64 characters."}])
    states.transition(step, "submitted", actor="human")
    states.transition(step, "waiting")
    step["ack_number"] = ack
    step["submitted_at"] = d.isoformat()
    step["preview_ready"] = False
    if ordinal == 1 and step["forum_id"] == "company_grievance":
        pc = case["case_json"].setdefault("prior_contact", {})
        pc.update(contacted_company=True, date=d.isoformat(), complaint_number=ack, got_reply=False,
                  reply_date=None, satisfied_with_reply=None)
        from .intake import refresh_derived
        refresh_derived(case)
    else:
        step["user_submitted"] = True
    repo.save_step(case_id, step)
    repo.add_timeline(case, "submitted", f"Acknowledgement {ack}", n=ordinal)
    repo.save_case(case)
    case = await planning.plan_case(case_id, use_llm=False, timeline=False)
    return case


# ------------------------------------------------------------ S4 (deterministic fake status)
def sandbox_status(complaint_number: str) -> dict:
    cn = complaint_number.strip()
    up = cn.upper()
    last = (clock.today() - timedelta(days=1)).isoformat()
    if "RJ" in up:
        text, remarks = "Rejected", "The bank has reviewed the complaint and found no error in the transaction."
    elif "RP" in up:
        text, remarks = "Replied", "A reply has been sent to the registered email address."
    elif "CL" in up:
        text, remarks = "Closed", "Complaint closed."
    else:
        text, remarks = "Under review", "Your complaint is being examined by the grievance team."
    return {"complaint_number": cn, "status_text": text, "last_updated": last, "remarks": remarks}


# ------------------------------------------------------------ E19
def _status_url(step: dict, portal: str, run_id: str) -> str:
    if portal == "sandbox":
        return (f"{get_settings().sandbox_public_url}/sandbox/status?complaint_number={step['ack_number']}"
                f"&session={run_id}")
    forum = repo.get_forum(step["forum_id"])
    url = forum.get("track_url")
    if step["forum_id"] == "company_grievance":
        url = (step.get("grievance_route") or {}).get("grievance_form_url")
    if not url:
        raise bad_request("No status page is known for this step. Use the sandbox or check the portal yourself.")
    return url


async def start_status_check(case_id: str, ordinal: int, portal: str | None) -> str:
    repo.get_case(case_id)
    step = repo.get_step(case_id, ordinal)
    states.assert_can_check_status(step)
    portal = portal or step.get("last_portal_mode") or "sandbox"
    probe_id = repo.new_id("run")
    url = _status_url(step, portal, probe_id)
    key = runs.portal_key(portal, url) + ":status"
    if runs.portal_busy(key):
        from ..errors import ApiError
        raise ApiError(409, "PORTAL_BUSY", "Another agent run is already active on this portal. Please wait.")
    run = repo.create_run(case_id=case_id, step_ordinal=ordinal, kind="status", portal_mode=portal, portal_url=url,
                          portal_key=key)
    url = _status_url(step, portal, run["id"])
    repo.update_run(run["id"], status="running", started_at=clock.now_iso(), portal_url=url)
    runs.acquire_portal(key, run["id"])
    bus.publish(case_id, "run_started", {"run_id": run["id"], "kind": "status", "step_ordinal": ordinal,
                                         "portal_url": url, "portal_mode": portal})
    runs.start(run["id"], _run_status(run["id"], case_id, ordinal, portal, url, key))
    return run["id"]


async def _run_status(run_id: str, case_id: str, ordinal: int, portal: str, url: str, key: str) -> None:
    relay = runs.Relay(run_id, case_id, url)
    step = repo.get_step(case_id, ordinal)
    ack = step["ack_number"]
    try:
        mock_result = None
        if get_settings().mock_mode:
            s = sandbox_status(ack) if portal == "sandbox" else None
            mock_result = ({"found": True, "status_text": s["status_text"], "last_updated": s["last_updated"],
                            "remarks": s["remarks"], "blocker": "none"} if s else
                           {"found": False, "status_text": "", "last_updated": "", "remarks": "", "blocker": "login"})
        complete = await tinyfish().run_sse(url, goals.g2_status(ack), on_event=relay,
                                            output_schema=goals.STATUS_SCHEMA, agent_config=goals.STATUS_AGENT_CONFIG,
                                            mock_fixture="status_sandbox", mock_result=mock_result)
        raw = complete.get("result") or {}
        try:
            norm = await gateway().run("P6_status", {"raw": raw})
        except Exception:
            from ..llm.mock_brain import normalize_status
            norm = normalize_status(raw)
        check = {"checked_at": clock.now_iso(), **{k: norm.get(k) for k in (
            "found", "status_text", "normalized_status", "last_updated", "remarks", "blocker")}}
        check["found"] = bool(check["found"])
        check["normalized_status"] = check["normalized_status"] or "unknown"
        case = repo.get_case(case_id)
        step = repo.get_step(case_id, ordinal)
        step["status_checks"] = [check, *(step.get("status_checks") or [])][:20]
        repo.save_step(case_id, step)
        repo.add_timeline(case, "status_checked", check.get("status_text"),
                          status=check.get("status_text") or check["normalized_status"])
        if check["normalized_status"] in ("replied", "rejected") and ordinal == 1:
            pc = case["case_json"].setdefault("prior_contact", {})
            pc["got_reply"] = True
            pc["reply_date"] = check.get("last_updated") or clock.today().isoformat()
            if check["normalized_status"] == "rejected":
                pc["satisfied_with_reply"] = False
            from .intake import refresh_derived
            refresh_derived(case)
        repo.save_case(case)
        runs.finish(run_id, "completed", result_json=check)
        bus.publish(case_id, "status_checked", {"step_ordinal": ordinal, "status_check": check})
        if check["normalized_status"] in ("replied", "rejected") and ordinal == 1:
            await planning.plan_case(case_id, use_llm=False, timeline=False)
        bus.publish(case_id, "run_completed", {"run_id": run_id, "kind": "status"})
    except TinyFishError as e:
        payload = runs.tinyfish_error_payload(e.code, e.message)
        runs.finish(run_id, "failed", error=payload)
        bus.publish(case_id, "run_failed", {"run_id": run_id, "error_code": payload["code"],
                                            "message": payload["message"], "retryable": payload["retryable"]})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("Status run %s crashed", run_id)
        code = getattr(e, "code", "INTERNAL")
        runs.finish(run_id, "failed", error={"code": code, "message": "Status check failed.", "retryable": True})
        bus.publish(case_id, "run_failed", {"run_id": run_id, "error_code": code, "message": "Status check failed.",
                                            "retryable": True})
    finally:
        runs.release_portal(key, run_id)


async def close_case(case_id: str, reason: str) -> dict:
    case = repo.get_case(case_id)
    if case["state"] in states.TERMINAL_CASE_STATES:
        raise illegal("This case is already closed.")
    if repo.active_runs_for_case(case_id):
        raise illegal("An agent run is still in progress. Cancel it first.")
    case["state"] = "RESOLVED" if reason == "resolved" else "CLOSED"
    if reason == "resolved":
        steps = repo.get_steps(case_id)
        for s in steps:
            if s["status"] in ("waiting", "due"):
                s["status"] = "done"
        repo.replace_steps(case_id, steps)
    repo.add_timeline(case, "closed", None, reason=reason)
    repo.save_case(case)
    bus.publish(case_id, "case_updated", {"state": case["state"]})
    return case
