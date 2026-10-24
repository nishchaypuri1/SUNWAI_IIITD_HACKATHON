"""Safety checks.

1. Post-run check for agent fills: the agent must never press a final Submit. Evidence sources:
   the agent's own `final_submit_clicked` flag, its PROGRESS sentences / step actions, and (sandbox) the
   sandbox page's own `submit_clicked` attempts log.
2. Deterministic draft checks (legal advice, outcome guarantees, threats, PII, security bypass) that run in
   addition to the P7 LLM checker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import pii

CLICK = r"\b(click(?:ed|ing|s)?|press(?:ed|ing|es)?|tap(?:ped|ping|s)?|hit(?:ting)?)\b"
SUBMIT_AFTER_REVIEW = re.compile(rf"(?i){CLICK}.*\b(submit|confirm|send|pay|proceed|final)\b")
SUBMIT_ANYTIME = re.compile(rf"(?i){CLICK}.*\b(submit|final submit|lodge complaint|register complaint)\b")
NEGATION = re.compile(
    r"(?i)(do not|don't|did not|didn't|not clicking|without clicking|without pressing|stopping before|"
    r"stopped before|stop before|will not|won't|never|avoid(?:ing|ed)?|not (?:click|press|tap)|instead of clicking|"
    r"refrain)"
)
REVIEW = re.compile(r"(?i)\b(review|preview|summary page|confirmation (?:page|screen)|check your details)\b")


@dataclass
class SafetyVerdict:
    ok: bool
    reason: str | None = None
    evidence: str | None = None
    hits: list[str] = field(default_factory=list)


def detect_submit_actions(messages: list[str]) -> list[str]:
    """Return the agent action sentences that look like pressing a final submit-type button."""
    hits: list[str] = []
    seen_review = False
    for msg in messages:
        if not msg:
            continue
        if not seen_review and REVIEW.search(msg):
            seen_review = True
        pattern = SUBMIT_AFTER_REVIEW if seen_review else SUBMIT_ANYTIME
        if pattern.search(msg) and not NEGATION.search(msg):
            hits.append(msg)
    return hits


def post_check(result: dict | None, messages: list[str], sandbox_submit_clicks: int = 0) -> SafetyVerdict:
    if sandbox_submit_clicks > 0:
        return SafetyVerdict(False, "The sandbox recorded a Submit click during this run.",
                             f"{sandbox_submit_clicks} submit_clicked attempt(s) logged by the sandbox page")
    if isinstance(result, dict) and result.get("final_submit_clicked") is True:
        return SafetyVerdict(False, "The agent reported that it clicked a final Submit button.",
                             "final_submit_clicked=true in the agent result")
    hits = detect_submit_actions(messages)
    if hits:
        return SafetyVerdict(False, "An agent action looks like pressing a final Submit/Confirm button.",
                             hits[0][:300], hits)
    return SafetyVerdict(True)


# ---------------- draft checks ----------------
_DRAFT_RULES: list[tuple[str, re.Pattern, str]] = [
    ("legal_advice", re.compile(r"(?i)\b(you are (legally )?entitled|legally (?:bound|obliged|liable)|"
                                r"under section \d+|as per law you must|this is illegal|criminal offen[cs]e)\b"),
     "Describe the facts and the request instead of legal conclusions."),
    ("legal_advice", re.compile(r"(?i)\b(guarantee[sd]?|will definitely (?:get|receive|win)|assured refund|"
                                r"certain to win)\b"),
     "Remove outcome guarantees."),
    ("threat", re.compile(r"(?i)\b(i will (?:sue|take legal action|go to court|file an? (?:fir|police case))|"
                          r"legal action against you|expose you|defame|you will regret|or else)\b"),
     "State the next official step calmly instead of a threat."),
    ("security_bypass", re.compile(r"(?i)\b(bypass|hack|captcha solver|share (?:my|the) otp|otp is|"
                                   r"password is)\b"),
     "Never include OTPs, passwords or ways around security checks."),
]


def check_draft_text(text: str, allow: list[str] | None = None) -> list[dict]:
    issues: list[dict] = []
    for typ, pattern, fix in _DRAFT_RULES:
        for m in pattern.finditer(text or ""):
            issues.append({"type": typ, "quote": m.group(0)[:120], "fix": fix})
    for hit in pii.find_raw_pii(text or "", allow=allow):
        issues.append({"type": "pii", "quote": hit, "fix": "Keep only the last 4 digits (XXXX1234)."})
    seen, out = set(), []
    for i in issues:
        key = (i["type"], i["quote"].lower())
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out
