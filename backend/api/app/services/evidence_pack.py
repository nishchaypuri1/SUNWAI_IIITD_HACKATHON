"""Evidence pack (E25): a Markdown file the user can keep or attach."""
from __future__ import annotations

from .. import clock, repo, schemas
from ..core import i18n
from . import rules


def build_markdown(case_id: str) -> str:
    case = repo.get_case(case_id)
    steps = repo.get_steps(case_id)
    cj = case["case_json"]
    cp = (cj.get("counterparty") or {}).get("name") or "—"
    amt = f"₹{cj['amount_inr']:,.0f}" if cj.get("amount_inr") else "—"
    lines = [
        f"# Sunwai evidence pack — case {case['id']}",
        "",
        f"Generated {clock.now_iso()} (demo clock {'simulated' if clock.offset_days() else 'real'}).",
        "",
        "## Case summary",
        f"- Summary: {cj.get('summary') or '—'}",
        f"- Against: {cp}",
        f"- Amount: {amt}",
        f"- Incident date: {i18n.fmt_date(cj['incident_date']) if cj.get('incident_date') else '—'}",
        f"- References: {', '.join(cj.get('reference_numbers') or []) or '—'}",
        "",
        "## Steps",
    ]
    attachments: list[str] = []
    for s in steps:
        forum = repo.get_forum(s["forum_id"])
        ref = rules.rule_ref(s["forum_id"]) or {}
        lines += [
            "",
            f"### Step {s['ordinal']}: {forum['name']}",
            f"- Status: {s['status']}",
            f"- Opens: {s.get('opens_at') or s.get('opens_when') or '—'}",
            f"- Last day to file: {('on or before ' + i18n.fmt_date(s['closes_at'])) if s.get('closes_at') else '—'}",
            f"- Wait ends: {s.get('due_at') or '—'}",
            f"- Acknowledgement number: {s.get('ack_number') or '—'} (submitted {s.get('submitted_at') or '—'})",
            f"- Needs verification: {'yes' if s.get('needs_verification') else 'no'}",
        ]
        if ref:
            lines.append(f"- Rule source: {ref.get('source_title') or '—'} — {ref.get('source_url') or 'stored copy'} "
                         f"(fetched {ref.get('fetched_at') or '—'}, {ref.get('freshness')})")
            if ref.get("evidence_snippet"):
                lines.append(f"- Official text: \"{ref['evidence_snippet']}\"")
        route = s.get("grievance_route")
        if route:
            lines.append(f"- Grievance form: {route.get('grievance_form_url') or '—'}; email: "
                         f"{route.get('grievance_email') or '—'}")
        for c in (s.get("status_checks") or [])[:3]:
            lines.append(f"- Status check {c['checked_at'][:10]}: {c.get('status_text') or c['normalized_status']}")
        d = s.get("draft")
        if d:
            lines += ["", f"**Draft — {d['subject']}**", "", "```", d["body"], "```"]
            attachments += d.get("attachments_to_mention") or []
    attach_lines = [f"- {a}" for a in dict.fromkeys(attachments)] or ["- Transaction proof"]
    lines += ["", "## Attach these", *attach_lines, ""]
    lines += ["## Timeline", *[f"- {t['at'][:16].replace('T', ' ')} — {t['title']}" for t in reversed(case["timeline"])]]
    lines += ["", "---", schemas.DISCLAIMER, ""]
    return "\n".join(lines)
