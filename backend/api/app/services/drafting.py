"""Drafting (E12/E13): P4 draft -> word limit -> P7 + deterministic safety checks -> placeholders."""
from __future__ import annotations

import re

from .. import clock, repo
from ..core import pii, safety, states
from ..events import bus
from ..llm.gateway import gateway

PLACEHOLDER = re.compile(r"\[please fill: ([^\]]+)\]")
MAX_WORDS = 250


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def step_context(case: dict, step: dict) -> dict:
    cj = case["case_json"]
    pc = cj.get("prior_contact") or {}
    steps = repo.get_steps(case["id"])
    prev = next((s for s in steps if s["ordinal"] == step["ordinal"] - 1), None)
    forum = repo.get_forum(step["forum_id"])
    ctx = {
        "forum_id": step["forum_id"], "forum_name": forum["name"], "closes_at": step.get("closes_at"),
        "prev_complaint_number": None, "prev_complaint_date": None, "wait_elapsed": False, "reply_date": None,
    }
    if prev:
        ctx["prev_complaint_number"] = prev.get("ack_number") or pc.get("complaint_number")
        ctx["prev_complaint_date"] = prev.get("submitted_at") or pc.get("date")
        due = clock.parse_date(prev.get("due_at"))
        ctx["wait_elapsed"] = bool(due and clock.today() >= due and pc.get("got_reply") is not True)
        ctx["reply_date"] = pc.get("reply_date") if pc.get("got_reply") else None
    return ctx


def _case_for_llm(case: dict) -> dict:
    cj = dict(case["case_json"])
    cj.pop("pii_flags", None)
    cj.pop("missing_fields", None)
    return cj


async def _safety(case: dict, subject: str, body: str) -> dict:
    cj = case["case_json"]
    allow = [*(cj.get("reference_numbers") or []), (cj.get("prior_contact") or {}).get("complaint_number") or ""]
    allow += [s.get("ack_number") or "" for s in repo.get_steps(case["id"])]
    issues = safety.check_draft_text(f"{subject}\n{body}", allow=[a for a in allow if a])
    try:
        out = await gateway().run("P7", {"case": _case_for_llm(case), "subject": subject, "body": body})
        for i in out.get("issues") or []:
            if not any(i.get("quote", "").lower() == x["quote"].lower() for x in issues):
                issues.append({"type": i["type"], "quote": str(i.get("quote", ""))[:200],
                               "fix": str(i.get("fix", ""))[:200]})
    except Exception:
        pass  # deterministic checks above still apply
    return {"ok": not issues, "issues": issues}


def _language(case: dict) -> str:
    return "hi" if case["language"] == "hi" else "en"


async def generate(case_id: str, ordinal: int, *, emit: bool = True) -> dict:
    case = repo.get_case(case_id)
    step = repo.get_step(case_id, ordinal)
    states.assert_can_draft(step)
    lang = _language(case)
    variables = {"case": _case_for_llm(case), "text": case["text_masked"], "step_context": step_context(case, step),
                 "language": lang, "want_hindi": False}
    out = await gateway().run("P4", variables)
    subject, body = pii.scrub(out["subject"]).text.strip(), pii.scrub(out["body"]).text.strip()
    if word_count(body) > MAX_WORDS:
        out = await gateway().run("P4", {**variables, "shorten": True})
        subject, body = pii.scrub(out["subject"]).text.strip(), pii.scrub(out["body"]).text.strip()
        if word_count(body) > MAX_WORDS:
            body = " ".join(body.split()[:MAX_WORDS])
    verdict = await _safety(case, subject, body)
    if not verdict["ok"]:
        retry = await gateway().run("P4", {**variables, "issues": verdict["issues"]})
        s2, b2 = pii.scrub(retry["subject"]).text.strip(), pii.scrub(retry["body"]).text.strip()
        if word_count(b2) <= MAX_WORDS:
            v2 = await _safety(case, s2, b2)
            if v2["ok"] or len(v2["issues"]) < len(verdict["issues"]):
                subject, body, verdict, out = s2, b2, v2, retry
    draft = {
        "subject": subject[:300], "body": body, "placeholders_to_fill": PLACEHOLDER.findall(body),
        "attachments_to_mention": [str(a) for a in (out.get("attachments_to_mention") or [])][:8],
        "language": lang, "word_count": word_count(body), "safety": verdict, "edited_by_user": False,
        "updated_at": clock.now_iso(),
    }
    step["draft"] = draft
    repo.save_step(case_id, step)
    repo.add_timeline(case, "draft_ready", None, n=ordinal)
    repo.save_case(case)
    if emit:
        bus.publish(case_id, "draft_ready", {"step_ordinal": ordinal})
    return draft


async def update(case_id: str, ordinal: int, subject: str, body: str) -> dict:
    case = repo.get_case(case_id)
    step = repo.get_step(case_id, ordinal)
    states.assert_can_draft(step)
    s = pii.scrub(subject)
    b = pii.scrub(body)
    verdict = await _safety(case, s.text, b.text)
    if s.flags or b.flags:
        verdict["issues"].append({"type": "pii", "quote": "(masked automatically)",
                                  "fix": "Sensitive numbers were reduced to their last 4 digits before saving."})
        verdict["ok"] = False
    prev = step.get("draft") or {}
    draft = {
        "subject": s.text.strip(), "body": b.text.strip(), "placeholders_to_fill": PLACEHOLDER.findall(b.text),
        "attachments_to_mention": prev.get("attachments_to_mention") or [], "language": _language(case),
        "word_count": word_count(b.text), "safety": verdict, "edited_by_user": True, "updated_at": clock.now_iso(),
    }
    step["draft"] = draft
    repo.save_step(case_id, step)
    repo.add_timeline(case, "draft_edited", None, n=ordinal)
    repo.save_case(case)
    bus.publish(case_id, "draft_ready", {"step_ordinal": ordinal})
    return draft
