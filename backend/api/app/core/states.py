"""Case + step state machines and transition guards (contract §4.1).

Only a human request to E18 may move a step to `submitted`; agent output never can.
"""
from __future__ import annotations

from ..errors import illegal

STEP_TRANSITIONS: dict[str, set[str]] = {
    "locked": {"open", "skipped", "expired", "locked"},
    "open": {"filling", "locked", "expired", "skipped", "open", "done"},
    "filling": {"review_ready", "blocked", "open"},
    "review_ready": {"submitted", "open", "filling"},
    "blocked": {"filling", "submitted", "open"},
    "submitted": {"waiting"},
    "waiting": {"due", "done", "waiting"},
    "due": {"done", "due"},
    "done": set(),
    "skipped": {"open", "locked"},
    "expired": {"open", "locked"},
}

TERMINAL_CASE_STATES = {"CLOSED", "RESOLVED"}
ACTIVE_RUN_STATUSES = {"queued", "running"}


def transition(step: dict, new: str, *, actor: str = "system") -> None:
    cur = step.get("status")
    if new == "submitted" and actor != "human":
        raise illegal("Only the user can mark a step as submitted.", step=step.get("ordinal"))
    if new not in STEP_TRANSITIONS.get(cur, set()):
        raise illegal(f"Step {step.get('ordinal')} cannot move from {cur} to {new}.",
                      step=step.get("ordinal"), status=cur, target=new)
    step["status"] = new


def assert_can_prefill(step: dict) -> None:
    if step.get("forum_id") == "consumer_commission":
        raise illegal("Consumer commission filings are never automated. Please file on e-Jagriti yourself.",
                      step=step["ordinal"])
    if step.get("status") not in ("open", "blocked"):
        raise illegal(f"Step {step['ordinal']} is not ready for pre-fill.", step=step["ordinal"],
                      status=step.get("status"))


def assert_can_submit(step: dict) -> None:
    if step.get("status") not in ("review_ready", "blocked"):
        raise illegal(f"Step {step['ordinal']} can be marked submitted only after the review screen or a "
                      "hand-off.", step=step["ordinal"], status=step.get("status"))


def assert_can_prepare_next(step: dict) -> None:
    st = step.get("status")
    if st == "due":
        return
    if st == "waiting":
        checks = step.get("status_checks") or []
        if checks and checks[0].get("normalized_status") in ("replied", "rejected"):
            return
    raise illegal(f"Step {step['ordinal']} is not due yet, so the next filing cannot be prepared.",
                  step=step["ordinal"], status=st)


def assert_can_check_status(step: dict) -> None:
    if step.get("status") not in ("submitted", "waiting", "due") or not step.get("ack_number"):
        raise illegal(f"Step {step['ordinal']} has no submitted complaint to check.", step=step["ordinal"],
                      status=step.get("status"))


def assert_can_draft(step: dict) -> None:
    if step.get("status") in ("skipped", "done", "expired"):
        raise illegal(f"Step {step['ordinal']} is {step.get('status')}; no draft is needed.",
                      step=step["ordinal"], status=step.get("status"))


def assert_can_discover(step: dict) -> None:
    if step.get("forum_id") != "company_grievance":
        raise illegal("Grievance discovery is only available for the company grievance step.",
                      step=step["ordinal"])


def derive_case_state(current: str, steps: list[dict]) -> str:
    """Case state = state of the furthest active step (see README 'Case state')."""
    if current in TERMINAL_CASE_STATES:
        return current
    if not steps:
        return current if current in ("NEW", "INTAKE_DONE") else "INTAKE_DONE"
    statuses = [s["status"] for s in steps]
    if "filling" in statuses:
        return "FILLING"
    if "review_ready" in statuses:
        return "REVIEW_READY"
    if "blocked" in statuses:
        return "BLOCKED"
    active = [s for s in steps if s["status"] not in ("locked", "skipped", "expired")]
    if not active:
        return "LADDER_READY"
    cur = active[-1]
    st = cur["status"]
    if st == "open":
        if cur.get("escalation_prepared"):
            return "ESCALATION_READY"
        prev = [s for s in active if s["ordinal"] < cur["ordinal"]]
        if prev and prev[-1]["status"] == "due":
            return "DUE"
        return "AWAITING_APPROVAL" if cur.get("preview_ready") else "LADDER_READY"
    return {"submitted": "SUBMITTED_BY_USER", "waiting": "WAITING", "due": "DUE", "done": "RESOLVED"}.get(
        st, "LADDER_READY")
