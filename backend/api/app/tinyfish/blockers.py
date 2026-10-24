"""Detect why an agent run could not proceed (login / OTP / CAPTCHA / bot wall / portal down)."""
from __future__ import annotations

import json
import re

BLOCKERS = {"login", "otp", "captcha", "portal_down", "form_not_found", "bot_challenge"}
_KEYWORDS = [
    ("otp", re.compile(r"(?i)\b(otp|one[- ]time password|verification code)\b")),
    ("captcha", re.compile(r"(?i)(captcha|verify (?:that )?you are (?:a )?human|i'?m not a robot)")),
    ("login", re.compile(r"(?i)\b(sign[ -]?in|log[ -]?in|login required|please log in|authentication required)\b")),
    ("portal_down", re.compile(r"(?i)\b(503|502|service unavailable|site (?:is )?down|under maintenance|"
                               r"could not load|page failed to load)\b")),
    ("form_not_found", re.compile(r"(?i)(form (?:was )?not found|could not find (?:the )?(?:complaint |grievance )?form)")),
]


def detect(result: dict | None, complete: dict | None, messages: list[str]) -> str | None:
    result = result if isinstance(result, dict) else {}
    complete = complete or {}
    b = result.get("blocker")
    if b in BLOCKERS:
        return b
    hint = complete.get("profile_hint") or {}
    reason = hint.get("reason") if isinstance(hint, dict) else None
    if reason == "auth_wall":
        return "login"
    if reason == "bot_challenge":
        return "bot_challenge"
    err = complete.get("error") or {}
    code = err.get("code") if isinstance(err, dict) else None
    if code == "SITE_BLOCKED":
        return "bot_challenge"
    if result.get("reached_review_screen") is True:
        return None
    text = " ".join([json.dumps({k: v for k, v in result.items() if k != "fields_filled"}, ensure_ascii=False),
                     *messages])
    for name, pat in _KEYWORDS:
        if pat.search(text):
            return name
    return None
