"""Prepare next filing (E20): P9 recommendation, overridden by the deterministic engine; draft for the next forum."""
from __future__ import annotations

import json
import logging
import re

from .. import clock, repo
from ..core import states
from ..errors import illegal
from ..events import bus
from ..llm.gateway import gateway
from . import drafting, planning, rules

log = logging.getLogger("sunwai.escalation")


async def prepare_next(case_id: str, ordinal: int) -> dict:
    case = repo.get_case(case_id)
    if case["state"] in states.TERMINAL_CASE_STATES:
        raise illegal("This case is closed.")
    step = repo.get_step(case_id, ordinal)
    states.assert_can_prepare_next(step)
    # make sure time-based statuses are current before deciding
    planning.recompute(case_id, emit=True)
    case = repo.get_case(case_id)
    steps = repo.get_steps(case_id)
    nxt = next((s for s in steps if s["ordinal"] > ordinal and s["status"] != "skipped"), None)
    today = clock.today()
    if nxt is None:
        engine_rec = "close" if (case["case_json"].get("prior_contact") or {}).get("satisfied_with_reply") else \
            "needs_user_input"
    elif nxt["status"] == "open":
        engine_rec = "escalate"
    elif nxt["status"] == "locked" and nxt.get("opens_at") and clock.parse_date(nxt["opens_at"]) > today:
        engine_rec = "wait_more"
    else:
        engine_rec = "needs_user_input"
    forum = repo.get_forum(nxt["forum_id"]) if nxt else None
    rule = rules.get_rule(nxt["forum_id"]) if nxt else {}
    engine = {
        "engine_recommendation": engine_rec, "next_forum_id": nxt["forum_id"] if nxt else None,
        "next_forum_name": forum["name"] if forum else None, "next_opens_at": nxt.get("opens_at") if nxt else None,
        "next_closes_at": nxt.get("closes_at") if nxt else None,
        "needs_verification": bool(nxt and nxt.get("needs_verification")),
        "documents_required": rule.get("documents_required") or [],
        "acks": [s["ack_number"] for s in steps if s.get("ack_number")],
    }
    history = [{"step": s["ordinal"], "forum": s["forum_id"], "status": s["status"], "ack": s.get("ack_number"),
                "submitted_at": s.get("submitted_at"), "status_checks": (s.get("status_checks") or [])[:3]}
               for s in steps]
    cj = {k: v for k, v in case["case_json"].items() if k != "pii_flags"}
    try:
        llm = await gateway().run("P9", {"case": cj, "history": history, "engine": engine,
                                         "rules": {"next": rule.get("scheme_name")}})
    except Exception as e:
        log.warning("P9 failed (%s); using engine reasoning", type(e).__name__)
        from ..llm.mock_brain import escalation as fallback
        llm = fallback(engine)
    from ..llm.mock_brain import escalation as fallback
    rec = engine_rec
    reasoning = llm.get("reasoning") or ""
    template = fallback(engine)["reasoning"]
    allowed = set(re.findall(r"\d+", template + " " + json.dumps(engine)))
    if llm.get("recommendation") != engine_rec:
        log.info("P9 suggested %s; engine decided %s", llm.get("recommendation"), engine_rec)
        reasoning = template
    elif not reasoning or not set(re.findall(r"\d+", reasoning)) <= allowed:
        reasoning = template   # dates/numbers must come from the engine
    checklist = list(dict.fromkeys([*(llm.get("evidence_pack_checklist") or []), *engine["documents_required"],
                                    *[f"Acknowledgement / complaint number {a}" for a in engine["acks"]]]))[:12]
    pack = {
        "recommendation": rec, "next_forum_id": engine["next_forum_id"],
        "filing_deadline": engine["next_closes_at"],          # always the engine's date
        "reasoning": reasoning[:600], "evidence_pack_checklist": checklist,
        "needs_verification": engine["needs_verification"], "draft": None,
    }
    if rec == "escalate" and nxt:
        if nxt["forum_id"] != "consumer_commission":
            pack["draft"] = await drafting.generate(case_id, nxt["ordinal"])
        nxt = repo.get_step(case_id, nxt["ordinal"])
        nxt["escalation_prepared"] = True
        nxt["escalation_pack"] = {k: v for k, v in pack.items() if k != "draft"}
        repo.save_step(case_id, nxt)
        case = repo.get_case(case_id)
        repo.add_timeline(case, "escalation_ready", forum["name"] if forum else None)
        case["state"] = states.derive_case_state(case["state"], repo.get_steps(case_id))
        repo.save_case(case)
        bus.publish(case_id, "case_updated", {"state": case["state"]})
    return pack
