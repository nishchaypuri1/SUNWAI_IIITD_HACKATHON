"""JSON schemas for every prompt output. The gateway validates each LLM response against these."""
from __future__ import annotations

_S = {"type": "string"}
_SN = {"type": ["string", "null"]}
_BN = {"type": ["boolean", "null"]}
_NN = {"type": ["number", "null"]}
_IN = {"type": ["integer", "null"]}
_SA = {"type": "array", "items": {"type": "string"}}

CASE_JSON = {
    "type": "object",
    "required": ["language", "category", "summary", "counterparty", "prior_contact"],
    "properties": {
        "language": {"enum": ["en", "hi", "hinglish"]},
        "category": {"enum": ["bank_payment", "ecommerce_refund", "travel", "telecom", "insurance", "other"]},
        "summary": _S,
        "amount_inr": _NN,
        "incident_date": _SN,
        "counterparty": {"type": "object", "properties": {
            "name": _SN,
            "type": {"enum": ["bank", "payment_app", "merchant", "airline", "telco", "insurer", "other", None]}}},
        "reference_numbers": _SA,
        "prior_contact": {"type": "object", "properties": {
            "contacted_company": _BN, "date": _SN, "complaint_number": _SN, "got_reply": _BN,
            "reply_date": _SN, "satisfied_with_reply": _BN}},
        "desired_outcome": {"enum": ["refund", "reversal", "replacement", "apology", "other", None]},
        "evidence_found": _SA,
        "missing_fields": _SA,
        "pii_flags": _SA,
    },
}

RULE_EXTRACTION = {
    "type": "object",
    "required": ["wait_days_before_escalation", "filing_window_days", "filing_window_counts_from", "evidence"],
    "properties": {
        "scheme_name": _SN,
        "effective_from": _SN,
        "wait_days_before_escalation": _IN,
        "filing_window_days": _IN,
        "filing_window_counts_from": {"enum": ["later_of_wait_end_or_last_reply", "company_reply", "end_of_wait",
                                               "incident", "unclear"]},
        "evidence": {"type": "object", "additionalProperties": _SN},
        "eligibility_conditions": _SA,
        "exclusions": _SA,
        "documents_required": _SA,
        "unknowns": _SA,
        "superseded_value_note": _SN,
        "confidence": {"enum": ["high", "medium", "low"]},
    },
}

WHY = {
    "type": "object",
    "required": ["steps"],
    "properties": {
        "steps": {"type": "array", "items": {"type": "object", "required": ["ordinal", "why", "why_hi"],
                                             "properties": {"ordinal": {"type": "integer"}, "why": _S,
                                                            "why_hi": _S}}},
        "order_check": _SA,
    },
}

DRAFT = {
    "type": "object",
    "required": ["subject", "body"],
    "properties": {"subject": _S, "body": _S, "attachments_to_mention": _SA, "subject_hi": _SN, "body_hi": _SN},
}

FIELD_MAP = {
    "type": "object",
    "required": ["field_map"],
    "properties": {
        "field_map": {"type": "array", "items": {"type": "object", "required": ["label", "value"],
                                                 "properties": {"label": _S, "value": _SN, "source": _SN}}},
        "warnings": _SA,
    },
}

FILL_RESULT = {
    "type": "object",
    "required": ["reached_review_screen", "fields_filled", "fields_missing", "blocker", "final_submit_clicked"],
    "properties": {
        "reached_review_screen": {"type": "boolean"},
        "page_url": _SN,
        "fields_filled": {"type": "array", "items": {"type": "object", "required": ["label"],
                                                     "properties": {"label": _S, "value": _SN}}},
        "fields_missing": _SA,
        "blocker": {"enum": ["none", "login", "otp", "captcha", "portal_down", "form_not_found", "bot_challenge",
                             None]},
        "final_submit_clicked": {"type": "boolean"},
        "notes": _SN,
    },
}

STATUS_RESULT = {
    "type": "object",
    "required": ["found", "normalized_status"],
    "properties": {
        "found": {"type": "boolean"},
        "status_text": _SN,
        "normalized_status": {"enum": ["received", "in_progress", "replied", "closed", "rejected", "unknown"]},
        "last_updated": _SN,
        "remarks": _SN,
        "blocker": {"enum": ["login", "otp", "captcha", "portal_down", "form_not_found", "bot_challenge", None]},
    },
}

SAFETY = {
    "type": "object",
    "required": ["ok", "issues"],
    "properties": {
        "ok": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "object", "required": ["type", "quote", "fix"], "properties": {
            "type": {"enum": ["legal_advice", "threat", "invented_fact", "pii", "security_bypass"]},
            "quote": _S, "fix": _S}}},
    },
}

ESCALATION = {
    "type": "object",
    "required": ["recommendation", "reasoning"],
    "properties": {
        "recommendation": {"enum": ["close", "escalate", "wait_more", "needs_user_input"]},
        "next_forum_id": _SN,
        "filing_deadline": _SN,
        "reasoning": _S,
        "evidence_pack_checklist": _SA,
        "needs_verification": {"type": "boolean"},
    },
}

BY_PROMPT = {
    "P1": CASE_JSON, "P2": RULE_EXTRACTION, "P3": WHY, "P4": DRAFT, "P5": FIELD_MAP, "P6_fill": FILL_RESULT,
    "P6_status": STATUS_RESULT, "P7": SAFETY, "P9": ESCALATION,
}
