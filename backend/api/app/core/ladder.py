"""Deterministic escalation-ladder engine. All date arithmetic lives here (never in an LLM).

Day-count convention: calendar days, `date + timedelta(days=n)`. "closes_at" is the last day to file
("on or before closes_at").

Banking / payments (RB-IOS 2026):
  step 1 company_grievance -> step 2 rbi_cms
  wait_end = C + wait_days (30); Ombudsman opens at wait_end, or earlier at the reply date R if the
  customer is not satisfied / was rejected; window closes `filing_window_days` (90) after the LATER of
  wait_end and R (counts_from = later_of_wait_end_or_last_reply).
General consumer:
  step 1 company_grievance -> step 2 nch -> step 3 consumer_commission (never automated).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import i18n

BANKING_TYPES = {"bank", "payment_app"}
OUT_OF_SCOPE = {"telecom", "insurance", "other"}


@dataclass
class RuleInfo:
    rule_id: str
    forum_id: str
    wait_days: int | None = None
    window_days: int | None = None
    counts_from: str = "unclear"
    effective_from: date | None = None
    freshness: str = "seed"
    verified: bool = False               # key values backed by evidence found in fetched official text
    fetched_at: str | None = None
    limitation_days: int | None = None   # consumer commission only, if verified


@dataclass
class StepPlan:
    ordinal: int
    forum_id: str
    status: str
    opens_at: date | None = None
    closes_at: date | None = None
    opens_when: str | None = None
    due_at: date | None = None
    needs_verification: bool = False
    rule_id: str | None = None
    ack_number: str | None = None
    submitted_at: date | None = None
    reason: str = ""
    ctx: dict[str, Any] = field(default_factory=dict)


@dataclass
class LadderResult:
    route: str
    steps: list[StepPlan]
    warnings: list[str]


def _d(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def is_banking(case_json: dict) -> bool:
    cp = (case_json.get("counterparty") or {})
    return case_json.get("category") == "bank_payment" or cp.get("type") in BANKING_TYPES


def _time_status(today: date, opens: date | None, closes: date | None) -> str:
    if opens is None or today < opens:
        return "locked"
    if closes is not None and today > closes:
        return "expired"
    return "open"


def _stale_warning(rule: RuleInfo | None, warnings: list[str]) -> None:
    if rule and rule.freshness in ("seed", "stale"):
        when = rule.fetched_at[:10] if rule.fetched_at else "seed data"
        msg = i18n.WARN["stale_rule"].format(date=when)
        if msg not in warnings:
            warnings.append(msg)


def _window_close(rule: RuleInfo, wait_end: date | None, reply: date | None, incident: date | None
                  ) -> date | None:
    if rule.window_days is None:
        return None
    cf = rule.counts_from
    if cf == "later_of_wait_end_or_last_reply":
        if wait_end is None:
            return None
        base = max(wait_end, reply) if reply else wait_end
    elif cf == "company_reply":
        base = reply or wait_end
    elif cf == "end_of_wait":
        base = wait_end
    elif cf == "incident":
        base = incident
    else:
        return None
    return base + timedelta(days=rule.window_days) if base else None


def _user_step(ordinal: int, forum_id: str, ov: dict, rule: RuleInfo | None, today: date) -> StepPlan:
    """A step the user filed themselves through Sunwai (ack number entered via E18)."""
    sub = _d(ov.get("submitted_at"))
    due = None
    if sub and rule and rule.wait_days is not None and forum_id != "rbi_cms":
        due = sub + timedelta(days=rule.wait_days)
    status = ov.get("status") if ov.get("status") in ("done",) else ("due" if due and today >= due else "waiting")
    return StepPlan(ordinal, forum_id, status, due_at=due, ack_number=ov.get("ack_number"), submitted_at=sub,
                    rule_id=rule.rule_id if rule else None, reason="user_submitted_waiting",
                    ctx={"submitted": sub, "ack": ov.get("ack_number") or "-"},
                    needs_verification=bool(rule and not rule.verified))


def _step1(cj: dict, wait: int | None, rule: RuleInfo | None, today: date) -> tuple[StepPlan, dict]:
    pc = cj.get("prior_contact") or {}
    company = (cj.get("counterparty") or {}).get("name")
    contacted = pc.get("contacted_company") is True
    C = _d(pc.get("date"))
    R = _d(pc.get("reply_date"))
    ctx: dict[str, Any] = {"company": company or "the company"}
    if company:
        ctx["company_hi"] = company
    info = {"contacted": contacted, "C": C, "R": R, "got_reply": pc.get("got_reply"),
            "satisfied": pc.get("satisfied_with_reply")}
    rid = rule.rule_id if rule else None
    if not contacted:
        return StepPlan(1, "company_grievance", "open", opens_at=today, rule_id=rid,
                        reason="cg_not_contacted", ctx=ctx), info
    due = C + timedelta(days=wait) if (C and wait is not None) else None
    ctx.update(complained=C, due=due)
    sp = StepPlan(1, "company_grievance", "waiting", opens_at=C, due_at=due, rule_id=rid,
                  ack_number=pc.get("complaint_number"), submitted_at=C, ctx=ctx)
    if pc.get("satisfied_with_reply") is True:
        sp.status, sp.reason = "done", "cg_done"
    elif pc.get("got_reply") is True:
        sp.status, sp.reason = "due", "cg_replied"
    elif due and today >= due:
        sp.status, sp.reason = "due", "cg_due_no_reply"
    elif C is None:
        sp.reason = "cg_waiting_no_date"
    elif due is None:
        sp.reason = "cg_waiting_open_ended"
    else:
        sp.reason = "cg_waiting"
    return sp, info


def plan(case_json: dict, rules: dict[str, RuleInfo], today: date,
         overrides: dict[int, dict] | None = None) -> LadderResult:
    overrides = overrides or {}
    warnings: list[str] = []
    category = case_json.get("category") or "other"
    incident = _d(case_json.get("incident_date"))

    if is_banking(case_json):
        rbi = rules.get("rbi_cms")
        cg = rules.get("company_grievance")
        wait = rbi.wait_days if (rbi and rbi.wait_days is not None) else (cg.wait_days if cg else None)
        s1, info = _step1(case_json, wait, cg or rbi, today)
        if 1 in overrides and overrides[1].get("submitted_at") and not info["contacted"]:
            s1 = _user_step(1, "company_grievance", overrides[1], cg, today)
        steps = [s1]
        _stale_warning(rbi, warnings)

        if 2 in overrides and overrides[2].get("submitted_at"):
            steps.append(_user_step(2, "rbi_cms", overrides[2], rbi, today))
            return LadderResult("banking", steps, warnings)

        s2 = StepPlan(2, "rbi_cms", "locked", rule_id=rbi.rule_id if rbi else None,
                      needs_verification=not (rbi and rbi.verified))
        C, R = info["C"], info["R"]
        if not info["contacted"]:
            s2.reason, s2.opens_when = "rbi_await", i18n.OPENS_WHEN["rbi_await"]
        elif info["satisfied"] is True:
            s2.status, s2.reason = "skipped", "rbi_skipped"
            warnings.append(i18n.WARN["satisfied"])
        elif C is None or wait is None:
            if info["got_reply"] is True:
                s2.status, s2.reason = "open", "rbi_open_reply_date_unknown"
                s2.opens_when = i18n.OPENS_WHEN["rbi_open_reply_date_unknown"]
            else:
                s2.reason, s2.opens_when = "rbi_date_unknown", i18n.OPENS_WHEN["rbi_date_unknown"]
            s2.needs_verification = True
        else:
            wait_end = C + timedelta(days=wait)
            replied_unhappy = info["got_reply"] is True and info["satisfied"] is not True
            if replied_unhappy and R is None:
                s2.status, s2.reason = "open", "rbi_open_reply_date_unknown"
                s2.opens_when = i18n.OPENS_WHEN["rbi_open_reply_date_unknown"]
            else:
                if replied_unhappy:
                    s2.opens_at = min(R, wait_end)
                    reason_open = "rbi_open_replied"
                else:
                    s2.opens_at = wait_end
                    reason_open = "rbi_open_no_reply"
                s2.closes_at = _window_close(rbi, wait_end, R if replied_unhappy else None, incident) if rbi else None
                s2.status = _time_status(today, s2.opens_at, s2.closes_at)
                if s2.closes_at is None:
                    s2.needs_verification = True
                    s2.reason = "rbi_window_unclear" if s2.status == "open" else "rbi_locked"
                elif s2.status == "open":
                    s2.reason = reason_open
                elif s2.status == "expired":
                    s2.reason = "rbi_expired"
                    warnings.append(i18n.WARN["expired"].format(
                        forum="the RBI Ombudsman", closes=i18n.fmt_date(s2.closes_at)))
                else:
                    s2.reason = "rbi_locked"
            if rbi and rbi.effective_from and C < rbi.effective_from:
                s2.needs_verification = True
                warnings.append(i18n.WARN["pre_2026"])
        s2.ctx = {"opens": s2.opens_at, "closes": s2.closes_at}
        if s2.status == "open" and s2.closes_at and (s2.closes_at - today).days < 7:
            warnings.append(i18n.WARN["seven_days"].format(forum="the RBI Ombudsman",
                                                           closes=i18n.fmt_date(s2.closes_at)))
        steps.append(s2)
        return LadderResult("banking", steps, warnings)

    # ---------------- general consumer ----------------
    nch = rules.get("nch")
    com = rules.get("consumer_commission")
    cg = rules.get("company_grievance")
    nch_wait = nch.wait_days if nch else None
    s1, info = _step1(case_json, nch_wait, cg, today)
    if 1 in overrides and overrides[1].get("submitted_at") and not info["contacted"]:
        s1 = _user_step(1, "company_grievance", overrides[1], nch, today)
    steps = [s1]
    if category in OUT_OF_SCOPE:
        warnings.append(i18n.WARN["out_of_scope"])
    company_done = info["contacted"] or bool(overrides.get(1, {}).get("submitted_at"))

    if 2 in overrides and overrides[2].get("submitted_at"):
        s2 = _user_step(2, "nch", overrides[2], nch, today)
    else:
        s2 = StepPlan(2, "nch", "locked", rule_id=nch.rule_id if nch else None,
                      needs_verification=not (nch and nch.verified))
        if not company_done:
            s2.reason, s2.opens_when = "nch_await", i18n.OPENS_WHEN["nch_await"]
        elif info["satisfied"] is True:
            s2.status, s2.reason = "skipped", "nch_skipped"
            warnings.append(i18n.WARN["satisfied"])
        elif nch_wait is not None and info["C"] is not None and nch and nch.verified:
            s2.opens_at = info["C"] + timedelta(days=nch_wait)
            s2.status = _time_status(today, s2.opens_at, None)
            s2.reason = "nch_open" if s2.status == "open" else "nch_locked"
        else:
            s2.status, s2.reason = "open", "nch_open"
            s2.opens_when = i18n.OPENS_WHEN["nch_open"]
            s2.needs_verification = True
            warnings.append(i18n.WARN["nch_unverified"])
        s2.ctx = {"opens": s2.opens_at}
    steps.append(s2)

    if category not in OUT_OF_SCOPE:
        s3 = StepPlan(3, "consumer_commission", "locked", rule_id=com.rule_id if com else None,
                      reason="commission_locked", opens_when=i18n.OPENS_WHEN["commission_locked"],
                      needs_verification=not (com and com.verified and com.limitation_days))
        if info["satisfied"] is True:
            s3.status, s3.reason, s3.opens_when = "skipped", "commission_skipped", None
        elif com and com.verified and com.limitation_days and incident:
            s3.closes_at = incident + timedelta(days=com.limitation_days)
        else:
            warnings.append(i18n.WARN["commission_unverified"])
        s3.ctx = {"closes": s3.closes_at}
        steps.append(s3)
    return LadderResult("consumer", steps, warnings)


def forums_for(case_json: dict) -> list[str]:
    if is_banking(case_json):
        return ["company_grievance", "rbi_cms"]
    if (case_json.get("category") or "other") in OUT_OF_SCOPE:
        return ["company_grievance", "nch"]
    return ["company_grievance", "nch", "consumer_commission"]
