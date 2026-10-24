"""Pre-fill (E14 preview, E15 run): TinyFish agent fills the portal form up to the review screen and STOPS.

Safety layers: goal text (G1) + output_schema flag + post-run submit detector + sandbox submit log +
state machine (only E18, a human request, can mark a step submitted).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from .. import clock, repo, seed
from ..config import get_settings
from ..core import i18n, pii, safety, states
from ..errors import ApiError, bad_request, illegal
from ..events import bus
from ..llm.gateway import gateway
from ..tinyfish import blockers, goals
from ..tinyfish.client import TinyFishError, tinyfish
from . import drafting, runs

log = logging.getLogger("sunwai.prefill")

GENERIC_LABELS = ["Complaint category", "Transaction / incident date", "Transaction reference", "Amount (₹)",
                  "Complaint description", "Previous complaint number (optional)"]


def sandbox_url(run_id: str | None = None) -> str:
    base = f"{get_settings().sandbox_public_url}/sandbox/grievance"
    return f"{base}?session={run_id}" if run_id else base


def _live_url(step: dict) -> str | None:
    if step["forum_id"] == "company_grievance":
        route = step.get("grievance_route") or {}
        return route.get("grievance_form_url") or route.get("page_url")
    forum = repo.get_forum(step["forum_id"])
    return forum.get("filing_url")


def _labels(step: dict, portal: str) -> tuple[list[str], str, bool]:
    if portal == "sandbox":
        f = seed.sandbox_fields()
        return [x["label"] for x in f["fields"]], f.get("date_format", "DD/MM/YYYY"), True
    path = Path(__file__).resolve().parent.parent.parent / "data" / "portal_adapters" / f"{step['forum_id']}.json"
    if path.is_file():
        f = json.loads(path.read_text(encoding="utf-8"))
        return [x["label"] for x in f["fields"]], f.get("date_format", "DD/MM/YYYY"), True
    return GENERIC_LABELS, "DD/MM/YYYY", False


async def preview(case_id: str, ordinal: int, portal: str) -> dict:
    if portal not in ("sandbox", "live"):
        raise bad_request("portal must be 'sandbox' or 'live'.")
    case = repo.get_case(case_id)
    step = repo.get_step(case_id, ordinal)
    if step["forum_id"] == "consumer_commission":
        raise illegal("Consumer commission filings are never automated. Please file on e-Jagriti yourself.")
    warnings: list[str] = []
    if portal == "sandbox":
        portal_url = sandbox_url()
        warnings.append("Sandbox: a clearly fictional demo bank form (Kanakpur Demo Bank). Nothing is sent to a "
                        "real bank or regulator.")
    else:
        portal_url = _live_url(step) or ""
        if not portal_url:
            raise illegal("No portal URL is known for this step yet. Run grievance discovery first, or use "
                                 "the sandbox.", step=ordinal)
        warnings.append("Live portals often ask for login or an OTP. The agent will stop there and hand over to you.")
    if not step.get("draft"):
        await drafting.generate(case_id, ordinal)
        step = repo.get_step(case_id, ordinal)
    labels, date_format, recorded = _labels(step, portal)
    if not recorded:
        warnings.append("No recorded field list for this portal yet; the agent will match fields by meaning.")
    draft = step.get("draft") or {}
    out = await gateway().run("P5", {"labels": labels, "date_format": date_format,
                                     "case": {k: v for k, v in case["case_json"].items() if k != "pii_flags"},
                                     "draft": {"subject": draft.get("subject"), "body": draft.get("body")}})
    cj = case["case_json"]
    known_refs = {*(cj.get("reference_numbers") or []), (cj.get("prior_contact") or {}).get("complaint_number")}
    known_refs |= {s.get("ack_number") for s in repo.get_steps(case_id)}
    field_map = []
    by_label = {f.get("label"): f for f in out.get("field_map", []) if isinstance(f, dict)}
    for label in labels:
        f = by_label.get(label) or {}
        value = f.get("value")
        if value in (None, ""):
            value = None
        elif str(value) in known_refs:
            value = str(value)
        else:
            value = pii.scrub(str(value)).text
        field_map.append({"label": label, "value": value, "source": f.get("source") if value else None})
    empty = [f["label"] for f in field_map if not f["value"]]
    if empty:
        warnings.append("These fields will be left empty for you to fill: " + ", ".join(empty) + ".")
    if draft.get("placeholders_to_fill"):
        warnings.append("The description still has [please fill: …] placeholders. Edit the draft first if you can.")
    if draft.get("safety") and not draft["safety"].get("ok"):
        warnings.append("The safety checker flagged the draft. Please review it before approving.")
    step["field_map"] = field_map
    step["preview_portal"] = portal
    step["preview_portal_url"] = portal_url
    step["preview_ready"] = True
    repo.save_step(case_id, step)
    case["state"] = states.derive_case_state(case["state"], repo.get_steps(case_id))
    repo.save_case(case)
    return {"portal_mode": portal, "portal_url": portal_url, "field_map": field_map,
            "draft_excerpt": (draft.get("body") or "")[:200], "warnings": warnings}


async def start(case_id: str, ordinal: int, approved: bool | None, portal: str) -> str:
    if approved is not True:
        raise ApiError(400, "APPROVAL_REQUIRED", "Please review the preview and approve before the agent starts.")
    case = repo.get_case(case_id)
    if case["state"] in states.TERMINAL_CASE_STATES:
        raise illegal("This case is closed.")
    step = repo.get_step(case_id, ordinal)
    states.assert_can_prefill(step)
    if not step.get("field_map") or step.get("preview_portal") != portal:
        await preview(case_id, ordinal, portal)
        step = repo.get_step(case_id, ordinal)
    portal_url = step.get("preview_portal_url") or (sandbox_url() if portal == "sandbox" else _live_url(step))
    if not portal_url:
        raise illegal("No portal URL is known for this step.")
    key = runs.portal_key(portal, portal_url)
    if runs.portal_busy(key):
        raise ApiError(409, "PORTAL_BUSY", "Another agent run is already active on this portal. Please wait.")
    run = repo.create_run(case_id=case_id, step_ordinal=ordinal, kind="fill", portal_mode=portal,
                          portal_url=portal_url, portal_key=key)
    runs.acquire_portal(key, run["id"])
    target = sandbox_url(run["id"]) if portal == "sandbox" else portal_url
    states.transition(step, "filling")
    step["latest_run_id"] = run["id"]
    step["last_portal_mode"] = portal
    repo.save_step(case_id, step)
    repo.update_run(run["id"], status="running", started_at=clock.now_iso())
    case["state"] = "FILLING"
    repo.add_timeline(case, "run_started", portal, n=ordinal)
    repo.save_case(case)
    bus.publish(case_id, "run_started", {"run_id": run["id"], "kind": "fill", "step_ordinal": ordinal,
                                         "portal_url": portal_url, "portal_mode": portal})
    bus.publish(case_id, "case_updated", {"state": "FILLING"})
    runs.start(run["id"], _run_fill(run["id"], case_id, ordinal, portal, target, portal_url, key))
    return run["id"]


def _mock_result(field_map: list[dict], page_url: str) -> dict:
    filled = [{"label": f["label"], "value": f["value"]} for f in field_map if f.get("value")]
    missing = [f["label"] for f in field_map if not f.get("value")]
    return {"reached_review_screen": True, "page_url": page_url + "#review", "fields_filled": filled,
            "fields_missing": missing, "blocker": "none", "final_submit_clicked": False,
            "notes": "Mock replay of a recorded sandbox run; stopped at the review screen."}


async def _run_fill(run_id: str, case_id: str, ordinal: int, portal: str, target: str, portal_url: str,
                    key: str) -> None:
    relay = runs.Relay(run_id, case_id, target)
    t0 = time.monotonic()
    real_start = clock.real_now_iso()
    tf = tinyfish()
    step = repo.get_step(case_id, ordinal)
    field_map = step.get("field_map") or []
    description = next((f["value"] for f in field_map if f["label"].lower().startswith("complaint description")),
                       None) or (step.get("draft") or {}).get("body")
    goal = goals.g1_fill(field_map, description)
    settings = get_settings()
    try:
        complete = await tf.run_sse(
            target, goal, on_event=relay, output_schema=goals.FILL_SCHEMA, agent_config=goals.FILL_AGENT_CONFIG,
            capture_config=goals.FILL_CAPTURE,
            proxy_country=(settings.tinyfish_proxy_country or None) if portal == "live" else None,
            mock_fixture="fill_sandbox" if portal == "sandbox" else "fill_blocked_login",
            mock_result=_mock_result(field_map, target) if portal == "sandbox" else None,
        )
        await _finish_fill(run_id, case_id, ordinal, portal, portal_url, complete, relay, real_start, t0)
    except TinyFishError as e:
        _fail(run_id, case_id, ordinal, runs.tinyfish_error_payload(e.code, e.message))
    except asyncio.CancelledError:
        _cancelled(run_id, case_id, ordinal)
        raise
    except Exception as e:
        log.exception("Fill run %s crashed", run_id)
        code = getattr(e, "code", "INTERNAL")
        _fail(run_id, case_id, ordinal, {"code": code, "message": "The agent run failed unexpectedly.",
                                         "retryable": True})
    finally:
        runs.release_portal(key, run_id)


async def _finish_fill(run_id: str, case_id: str, ordinal: int, portal: str, portal_url: str, complete: dict,
                       relay: runs.Relay, real_start: str, t0: float) -> None:
    tf = tinyfish()
    raw_result = complete.get("result")
    result: dict | None = None
    if isinstance(raw_result, dict):
        try:
            import jsonschema

            from ..llm.schemas import FILL_RESULT
            jsonschema.validate(raw_result, FILL_RESULT)
            result = raw_result
        except Exception:
            result = None
    if result is None and raw_result is not None:
        try:
            result = await gateway().run("P6_fill", {"raw": raw_result})
        except Exception:
            result = None
    # Evidence for the safety check: PROGRESS sentences + TinyFish step actions (best effort)
    tf_run_id = repo.get_run(run_id).get("tinyfish_run_id")
    step_actions: list[str] = []
    video_url, screenshots = None, []
    if tf_run_id:
        try:
            info = await tf.get_run(tf_run_id)
            video_url = info.get("video_url")
            for s in info.get("steps") or []:
                if s.get("action"):
                    step_actions.append(str(s["action"]))
                if s.get("screenshot"):
                    screenshots.append(str(s["screenshot"]))
        except Exception as e:
            log.info("get_run failed for %s: %s", tf_run_id, type(e).__name__)
    real_end = clock.real_now_iso()
    clicks = repo.sandbox_submit_clicks(run_id, real_start, real_end) if portal == "sandbox" else 0
    verdict = safety.post_check(result, relay.messages + step_actions, clicks)
    blocker = blockers.detect(result, complete, relay.messages)
    status = complete.get("status")
    field_map = repo.get_step(case_id, ordinal).get("field_map") or []
    filled_labels = {f["label"] for f in (result or {}).get("fields_filled", [])}
    packet = {
        "reached_review_screen": bool(result and result.get("reached_review_screen")),
        "stopped_before_submit": verdict.ok,
        "safety_flagged": not verdict.ok,
        "portal_mode": portal,
        "portal_url": portal_url,
        "page_url": (result or {}).get("page_url"),
        "fields": [{"label": f["label"], "value": f["value"], "filled": f["label"] in filled_labels,
                    "source": f.get("source")} for f in field_map],
        "fields_missing": (result or {}).get("fields_missing", []),
        "blocker": blocker,
        "blocker_message": i18n.BLOCKER_MESSAGE if blocker else None,
        "notes": (result or {}).get("notes"),
        "screenshots": screenshots[:20],
        "video_url": video_url,
        "generated_at": clock.now_iso(),
    }
    case = repo.get_case(case_id)
    step = repo.get_step(case_id, ordinal)
    step["review_packet"] = packet
    seconds = round(time.monotonic() - t0, 1)
    if not verdict.ok:
        states.transition(step, "blocked")
        runs.finish(run_id, "safety_flagged", result_json=result, video_url=video_url, screenshots_json=screenshots)
        repo.add_timeline(case, "safety_flagged", verdict.reason)
        _save(case, step)
        bus.publish(case_id, "safety_flagged", {"run_id": run_id, "step_ordinal": ordinal, "reason": verdict.reason,
                                                "evidence": verdict.evidence})
    elif blocker:
        states.transition(step, "blocked")
        runs.finish(run_id, "blocked", result_json=result, video_url=video_url, screenshots_json=screenshots)
        repo.add_timeline(case, "blocked", blocker)
        _save(case, step)
        bus.publish(case_id, "blocker", {"run_id": run_id, "step_ordinal": ordinal, "blocker": blocker,
                                         "message": i18n.BLOCKER_MESSAGE, "portal_url": portal_url})
    elif status == "COMPLETED" and packet["reached_review_screen"]:
        states.transition(step, "review_ready")
        runs.finish(run_id, "completed", result_json=result, video_url=video_url, screenshots_json=screenshots)
        repo.add_timeline(case, "review_ready")
        _save(case, step)
        bus.publish(case_id, "review_ready", {"run_id": run_id, "step_ordinal": ordinal, "review_packet": packet})
    else:
        err = complete.get("error") or {}
        code = err.get("code") if isinstance(err, dict) and err.get("code") else (
            "CANCELLED" if status == "CANCELLED" else "TASK_FAILED")
        _fail(run_id, case_id, ordinal, runs.tinyfish_error_payload(code, "The agent did not reach the review screen."),
              packet=packet)
        _log_live(portal, run_id, packet, field_map, result, clicks, seconds)
        return
    _log_live(portal, run_id, packet, field_map, result, clicks, seconds)
    bus.publish(case_id, "run_completed", {"run_id": run_id, "kind": "fill"})
    bus.publish(case_id, "case_updated", {"state": repo.get_case(case_id)["state"]})


def _save(case: dict, step: dict) -> None:
    repo.save_step(case["id"], step)
    case["state"] = states.derive_case_state(case["state"], repo.get_steps(case["id"]))
    repo.save_case(case)


def _fail(run_id: str, case_id: str, ordinal: int, payload: dict, packet: dict | None = None) -> None:
    runs.finish(run_id, "failed", error=payload)
    case = repo.get_case(case_id)
    step = repo.get_step(case_id, ordinal)
    if step["status"] == "filling":
        states.transition(step, "open")
    if packet:
        step["review_packet"] = packet
    repo.add_timeline(case, "run_failed", payload["message"])
    _save(case, step)
    bus.publish(case_id, "run_failed", {"run_id": run_id, "error_code": payload["code"], "message": payload["message"],
                                        "retryable": payload["retryable"]})
    bus.publish(case_id, "case_updated", {"state": repo.get_case(case_id)["state"]})


def _cancelled(run_id: str, case_id: str, ordinal: int) -> None:
    run = repo.get_run(run_id)
    if run["status"] not in ("cancelled",):
        runs.finish(run_id, "cancelled", error={"code": "CANCELLED", "message": "Run cancelled.", "retryable": True})
    case = repo.get_case(case_id)
    step = repo.get_step(case_id, ordinal)
    if step["status"] == "filling":
        states.transition(step, "open")
    repo.add_timeline(case, "run_cancelled")
    _save(case, step)


def _log_live(portal: str, run_id: str, packet: dict, field_map: list[dict], result: dict | None, clicks: int,
              seconds: float) -> None:
    """Live sandbox runs feed `make eval` (submit clicks, fields correct, seconds to review packet)."""
    s = get_settings()
    if s.mock_mode or portal != "sandbox":
        return
    expected = {f["label"]: (f.get("value") or "").strip().lower() for f in field_map if f.get("value")}
    got = {f["label"]: (f.get("value") or "").strip().lower() for f in (result or {}).get("fields_filled", [])}
    correct = sum(1 for k, v in expected.items() if got.get(k) == v or (v and got.get(k, "").startswith(v[:40])))
    row = {"run_id": run_id, "at": clock.real_now_iso(), "reached_review": packet["reached_review_screen"],
           "submit_clicks": clicks, "safety_flagged": packet["safety_flagged"], "seconds": seconds,
           "fields_expected": len(expected), "fields_correct": correct}
    path = Path(s.eval_dir) / "live_runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def cancel(run_id: str) -> None:
    run = repo.get_run(run_id)
    if run["status"] not in states.ACTIVE_RUN_STATUSES:
        return
    runs.finish(run_id, "cancelled", error={"code": "CANCELLED", "message": "Run cancelled by user.",
                                            "retryable": True})
    if run.get("tinyfish_run_id"):
        async def _remote() -> None:
            try:
                await tinyfish().cancel(run["tinyfish_run_id"])
            except Exception:
                pass
        asyncio.get_running_loop().create_task(_remote())
    was_running = runs.cancel_task(run_id)
    runs.release_portal(run.get("portal_key"), run_id)
    if run.get("case_id") and run.get("step_ordinal") and run["kind"] == "fill":
        if not was_running:
            _cancelled(run_id, run["case_id"], run["step_ordinal"])
        bus.publish(run["case_id"], "run_failed", {"run_id": run_id, "error_code": "CANCELLED",
                                                   "message": "Run cancelled by user.", "retryable": True})
    elif run.get("case_id"):
        bus.publish(run["case_id"], "run_failed", {"run_id": run_id, "error_code": "CANCELLED",
                                                   "message": "Run cancelled by user.", "retryable": True})

