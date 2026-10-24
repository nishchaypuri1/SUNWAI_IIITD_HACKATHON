"""Planning: run the deterministic ladder, merge with existing step state, write why-sentences.

`plan_case` (E9 / E8 / E18 / status replies) may ask the LLM (P3) for nicer why-sentences; dates always come
from core.ladder. `recompute` is the LLM-free variant used by the demo clock, the due sweep and rule refreshes.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from .. import clock, repo
from ..core import i18n, ladder, states
from ..errors import illegal
from ..events import bus
from ..llm.gateway import gateway
from . import rules

log = logging.getLogger("sunwai.planning")

PRESERVE = ["grievance_route", "draft", "review_packet", "latest_run_id", "status_checks", "user_submitted",
            "preview_ready", "escalation_prepared", "field_map", "preview_portal", "escalation_pack",
            "last_portal_mode"]
STICKY = {"filling", "review_ready", "blocked"}


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date) else v


def _overrides(existing: list[dict]) -> dict[int, dict]:
    out = {}
    for s in existing:
        if s.get("user_submitted"):
            out[s["ordinal"]] = {"submitted_at": s.get("submitted_at"), "ack_number": s.get("ack_number"),
                                 "status": "done" if s.get("status") == "done" else None}
    return out


def _merge(case: dict, existing: list[dict], result: ladder.LadderResult) -> tuple[list[dict], list[dict]]:
    by_ord = {s["ordinal"]: s for s in existing}
    company = (case["case_json"].get("counterparty") or {}).get("name")
    new_steps, became_due = [], []
    for sp in result.steps:
        old = by_ord.get(sp.ordinal)
        if old and old.get("forum_id") != sp.forum_id:
            old = None
        action, action_hi = i18n.action(sp.forum_id, company)
        ctx = {k: _iso(v) for k, v in sp.ctx.items()}
        why_en, why_hi = i18n.why(sp.reason, sp.ctx)
        step = {
            "ordinal": sp.ordinal, "forum_id": sp.forum_id, "status": sp.status,
            "opens_at": _iso(sp.opens_at), "closes_at": _iso(sp.closes_at), "opens_when": sp.opens_when,
            "due_at": _iso(sp.due_at), "needs_verification": sp.needs_verification, "rule_id": sp.rule_id,
            "ack_number": sp.ack_number, "submitted_at": _iso(sp.submitted_at), "reason": sp.reason, "ctx": ctx,
            "action": action, "action_hi": action_hi, "why": why_en, "why_hi": why_hi, "why_source": "template",
            "status_checks": [],
        }
        if old:
            for k in PRESERVE:
                if k in old:
                    step[k] = old[k]
            if old.get("reason") == sp.reason and old.get("ctx") == ctx and old.get("why_source") == "llm":
                step["why"], step["why_hi"], step["why_source"] = old["why"], old["why_hi"], "llm"
            if old.get("status") in STICKY and sp.status == "open":
                step["status"] = old["status"]
            if old.get("status") == "waiting" and step["status"] == "due":
                became_due.append(step)
        new_steps.append(step)
    return new_steps, became_due


async def _llm_why(case: dict, steps: list[dict]) -> None:
    payload = [{"ordinal": s["ordinal"], "forum": s["forum_id"], "status": s["status"], "opens_at": s["opens_at"],
                "closes_at": s["closes_at"], "due_at": s["due_at"], "reason": s["reason"],
                "template_why": s["why"], "template_why_hi": s["why_hi"]} for s in steps]
    try:
        out = await gateway().run("P3", {"case": _case_for_llm(case), "steps": payload})
    except Exception as e:  # why-sentences are cosmetic; never fail planning because of them
        log.warning("P3 failed (%s); keeping template sentences", type(e).__name__)
        return
    for item in out.get("steps", []):
        step = next((s for s in steps if s["ordinal"] == item.get("ordinal")), None)
        if not step:
            continue
        why, why_hi = (item.get("why") or "").strip(), (item.get("why_hi") or "").strip()
        # dates come from the engine: reject LLM sentences that introduce numbers the template does not have
        allowed = set(re.findall(r"\d+", step["why"] + " " + step["why_hi"]))
        if why and why_hi and set(re.findall(r"\d+", why + " " + why_hi)) <= allowed:
            step["why"], step["why_hi"] = why[:400], why_hi[:400]
            step["why_source"] = "llm"
    for oc in out.get("order_check") or []:
        log.info("P3 order_check (engine order kept): %s", oc)


def _case_for_llm(case: dict) -> dict:
    cj = dict(case["case_json"])
    cj.pop("pii_flags", None)
    return cj


def _apply(case: dict, existing: list[dict], *, emit: bool) -> tuple[list[dict], list[dict]]:
    result = ladder.plan(case["case_json"], rules.all_rule_infos(), clock.today(), _overrides(existing))
    steps, became_due = _merge(case, existing, result)
    intake_w = case.get("meta", {}).get("intake_warnings", [])
    extra = case.get("meta", {}).get("extra_warnings", [])
    case["warnings"] = list(dict.fromkeys([*intake_w, *result.warnings, *extra]))
    return steps, became_due


def _finish(case: dict, steps: list[dict], became_due: list[dict], *, emit: bool, force_event: bool = False) -> None:
    old_state = case["state"]
    for s in became_due:
        repo.add_timeline(case, "step_due", None, n=s["ordinal"])
    case["state"] = states.derive_case_state(case["state"], steps)
    repo.replace_steps(case["id"], steps)
    repo.save_case(case)
    if emit:
        for s in became_due:
            bus.publish(case["id"], "step_due", {"step_ordinal": s["ordinal"], "due_at": s["due_at"]})
        if case["state"] != old_state or became_due or force_event:
            bus.publish(case["id"], "case_updated", {"state": case["state"]})


async def plan_case(case_id: str, *, use_llm: bool = True, timeline: bool = True) -> dict:
    case = repo.get_case(case_id)
    if case["state"] in states.TERMINAL_CASE_STATES:
        raise illegal("This case is closed.")
    if any(r["kind"] == "fill" for r in repo.active_runs_for_case(case_id)):
        raise illegal("An agent run is in progress for this case; wait for it to finish.")
    existing = repo.get_steps(case_id)
    steps, became_due = _apply(case, existing, emit=True)
    if use_llm:
        await _llm_why(case, steps)
    if timeline and not existing:
        repo.add_timeline(case, "plan_ready")
    _finish(case, steps, became_due, emit=True, force_event=True)
    return case


def recompute(case_id: str, *, emit: bool = True) -> dict:
    case = repo.get_case(case_id)
    existing = repo.get_steps(case_id)
    if not existing or case["state"] in states.TERMINAL_CASE_STATES:
        return case
    steps, became_due = _apply(case, existing, emit=emit)
    _finish(case, steps, became_due, emit=emit)
    return case


def recompute_all(rule_changed_forum: str | None = None) -> None:
    for case in repo.list_cases():
        if case["state"] in states.TERMINAL_CASE_STATES:
            continue
        steps = repo.get_steps(case["id"])
        if not steps:
            continue
        if rule_changed_forum and any(s["forum_id"] == rule_changed_forum for s in steps):
            meta = case.setdefault("meta", {})
            msg = (f"The official rule for this case changed ({rule_changed_forum}); dates were recalculated. "
                   "Please re-check before filing.")
            meta["extra_warnings"] = list(dict.fromkeys([*meta.get("extra_warnings", []), msg]))
            repo.add_timeline(case, "rule_changed", msg)
            repo.save_case(case)
        try:
            recompute(case["id"])
        except Exception:
            log.exception("recompute failed for %s", case["id"])


def sweep() -> None:
    """Due-date sweep: time-based status changes after the demo clock moves (and every 10 minutes)."""
    recompute_all()
