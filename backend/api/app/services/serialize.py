"""Build contract objects (schemas.Case, Step, Run, CaseSummary) from stored dicts."""
from __future__ import annotations

from datetime import date
from typing import Any

from .. import clock, repo, schemas
from . import rules


def run_out(run: dict | None) -> schemas.Run | None:
    if not run:
        return None
    err = run.get("error_json")
    return schemas.Run(
        id=run["id"], kind=run["kind"], status=run["status"], step_ordinal=run.get("step_ordinal"),
        tinyfish_run_id=run.get("tinyfish_run_id"), streaming_url=run.get("streaming_url"),
        video_url=run.get("video_url"), started_at=run.get("started_at"), ended_at=run.get("ended_at"),
        events_count=int(run.get("raw_events_count") or 0),
        error=schemas.RunError(**err) if isinstance(err, dict) and err.get("code") else None,
    )


def run_detail(run: dict) -> schemas.RunDetail:
    base = run_out(run)
    assert base is not None
    events = [schemas.RunEventOut(seq=e["seq"], tf_type=e["tf_type"], message=e["message"], at=e["at"])
              for e in repo.run_events(run["id"])]
    return schemas.RunDetail(**base.model_dump(), events=events)


def _days(d: str | None, today: date, clamp: bool) -> int | None:
    dd = clock.parse_date(d)
    if dd is None:
        return None
    n = (dd - today).days
    return max(0, n) if clamp else n


def step_out(step: dict, today: date, forums: dict[str, dict], refs: dict[str, Any]) -> schemas.Step:
    fid = step["forum_id"]
    forum = dict(forums.get(fid) or repo.get_forum(fid))
    route = step.get("grievance_route")
    if fid == "company_grievance" and route:
        forum["filing_url"] = route.get("grievance_form_url") or forum.get("filing_url")
        forum["official_url"] = route.get("page_url") or forum.get("official_url")
    if fid not in refs:
        refs[fid] = rules.rule_ref(fid)
    return schemas.Step(
        ordinal=step["ordinal"], forum=schemas.Forum(**forum), action=step.get("action", ""),
        action_hi=step.get("action_hi", ""), why=step.get("why", ""), why_hi=step.get("why_hi", ""),
        status=step["status"], opens_at=step.get("opens_at"), closes_at=step.get("closes_at"),
        opens_when=step.get("opens_when"), due_at=step.get("due_at"),
        days_until_open=_days(step.get("opens_at"), today, True),
        days_until_close=_days(step.get("closes_at"), today, False),
        needs_verification=bool(step.get("needs_verification")),
        rule=schemas.RuleRef(**refs[fid]) if refs[fid] else None,
        grievance_route=schemas.GrievanceRoute(**route) if route else None,
        draft=schemas.Draft(**step["draft"]) if step.get("draft") else None,
        latest_run=run_out(repo.find_run(step.get("latest_run_id"))),
        review_packet=schemas.ReviewPacket(**step["review_packet"]) if step.get("review_packet") else None,
        ack_number=step.get("ack_number"), submitted_at=step.get("submitted_at"),
        status_checks=[schemas.StatusCheck(**c) for c in (step.get("status_checks") or [])],
    )


def case_out(case: dict, steps: list[dict] | None = None) -> schemas.Case:
    steps = repo.get_steps(case["id"]) if steps is None else steps
    today = clock.today()
    forums = {f["id"]: f for f in repo.all_forums()}
    refs: dict[str, Any] = {}
    cj = dict(case["case_json"])
    return schemas.Case(
        id=case["id"], created_at=case["created_at"], updated_at=case["updated_at"], state=case["state"],
        language=case["language"], case_json=schemas.CaseJson(**cj),
        missing_fields=list(cj.get("missing_fields") or []),
        questions=[schemas.Question(**q) for q in case["questions"]],
        steps=[step_out(s, today, forums, refs) for s in steps], warnings=case["warnings"],
        timeline=[schemas.TimelineItem(**t) for t in case["timeline"]], disclaimer=schemas.DISCLAIMER,
    )


def summary_out(case: dict, steps: list[dict]) -> schemas.CaseSummary:
    today = clock.today()
    upcoming: list[str] = []
    for s in steps:
        if s["status"] in ("open", "locked") and s.get("closes_at") and s["closes_at"] >= today.isoformat():
            upcoming.append(s["closes_at"])
        if s["status"] == "waiting" and s.get("due_at"):
            upcoming.append(s["due_at"])
    active = [s for s in steps if s["status"] not in ("locked", "skipped", "expired")]
    cj = case["case_json"]
    return schemas.CaseSummary(
        id=case["id"], created_at=case["created_at"], state=case["state"], summary=cj.get("summary") or "",
        counterparty_name=(cj.get("counterparty") or {}).get("name"), amount_inr=cj.get("amount_inr"),
        next_deadline=min(upcoming) if upcoming else None, current_step=active[-1]["ordinal"] if active else None,
    )
