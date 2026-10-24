"""Deterministic English + Hindi strings for server-side text (questions, actions, why-sentences, timeline).
No LLM is involved, so these are always available and identical in mock and live mode.
"""
from __future__ import annotations

from datetime import date
from typing import Any

MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर",
             "दिसंबर"]


def fmt_date(d: date | str | None, lang: str = "en") -> str:
    if d is None:
        return "?"
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    if lang == "hi":
        return f"{d.day} {MONTHS_HI[d.month - 1]} {d.year}"
    return f"{d.day} {MONTHS_EN[d.month - 1]} {d.year}"


# ---------------- questions ----------------
YES_NO = [
    {"value": "true", "label": "Yes", "label_hi": "हाँ"},
    {"value": "false", "label": "No", "label_hi": "नहीं"},
]

QUESTIONS: dict[str, dict[str, Any]] = {
    "counterparty.name": {
        "question": "Which company, bank or app is this complaint against?",
        "question_hi": "यह शिकायत किस कंपनी, बैंक या ऐप के ख़िलाफ़ है?",
        "input": "text",
    },
    "prior_contact.contacted_company": {
        "question": "Have you already complained to the company or bank?",
        "question_hi": "क्या आपने पहले ही कंपनी या बैंक से शिकायत की है?",
        "input": "boolean", "options": YES_NO,
    },
    "prior_contact.date": {
        "question": "On what date did the company or bank receive your complaint?",
        "question_hi": "कंपनी या बैंक को आपकी शिकायत किस तारीख़ को मिली?",
        "input": "date",
    },
    "prior_contact.got_reply": {
        "question": "Did they reply to your complaint?",
        "question_hi": "क्या उन्होंने आपकी शिकायत का जवाब दिया?",
        "input": "boolean", "options": YES_NO,
    },
    "prior_contact.reply_date": {
        "question": "On what date did they last reply?",
        "question_hi": "उन्होंने आख़िरी बार किस तारीख़ को जवाब दिया?",
        "input": "date",
    },
    "prior_contact.satisfied_with_reply": {
        "question": "Are you satisfied with their reply?",
        "question_hi": "क्या आप उनके जवाब से संतुष्ट हैं?",
        "input": "boolean", "options": YES_NO,
    },
    "incident_date": {
        "question": "On what date did the problem happen (transaction or incident date)?",
        "question_hi": "समस्या किस तारीख़ को हुई (लेन-देन या घटना की तारीख़)?",
        "input": "date",
    },
    "amount_inr": {
        "question": "What amount (in ₹) is involved?",
        "question_hi": "कितनी राशि (₹ में) का मामला है?",
        "input": "number",
    },
}

QUESTION_ORDER = [
    "counterparty.name", "prior_contact.contacted_company", "prior_contact.date", "prior_contact.got_reply",
    "prior_contact.reply_date", "prior_contact.satisfied_with_reply", "incident_date",
]

CONFIRM_PREFIX = ("Please check this date: ", "कृपया यह तारीख़ जाँचें: ")

# ---------------- actions ----------------
ACTIONS = {
    "company_grievance": ("Complain to {company}", "{company_hi} से शिकायत करें"),
    "rbi_cms": ("File with the RBI Ombudsman", "आरबीआई लोकपाल के पास शिकायत दर्ज करें"),
    "nch": ("Register with the National Consumer Helpline", "राष्ट्रीय उपभोक्ता हेल्पलाइन पर शिकायत दर्ज करें"),
    "consumer_commission": ("Approach the consumer commission (e-Jagriti)",
                            "उपभोक्ता आयोग (ई-जागृति) से संपर्क करें"),
}

# ---------------- why sentences (keyed by ladder reason) ----------------
WHY: dict[str, tuple[str, str]] = {
    "cg_not_contacted": (
        "The company must get a chance to fix the problem first. Complain to {company} and keep the complaint number.",
        "पहले कंपनी को समस्या ठीक करने का मौक़ा देना ज़रूरी है। {company_hi} से शिकायत करें और शिकायत संख्या संभालकर रखें।"),
    "cg_waiting": (
        "You complained on {complained}. They have until {due} to reply.",
        "आपने {complained_hi} को शिकायत की थी। उनके पास {due_hi} तक जवाब देने का समय है।"),
    "cg_waiting_no_date": (
        "You have complained. Add the date they received it so we can track the reply deadline.",
        "आपने शिकायत कर दी है। उन्हें शिकायत किस तारीख़ को मिली, यह बताएँ ताकि जवाब की समय-सीमा देखी जा सके।"),
    "cg_waiting_open_ended": (
        "You complained on {complained}. Wait for their reply and keep the complaint number safe.",
        "आपने {complained_hi} को शिकायत की थी। उनके जवाब का इंतज़ार करें और शिकायत संख्या संभालकर रखें।"),
    "cg_due_no_reply": (
        "The reply period ended on {due} without a resolution, so you can escalate.",
        "जवाब की अवधि {due_hi} को ख़त्म हो गई और समस्या हल नहीं हुई, इसलिए आप आगे शिकायत कर सकते हैं।"),
    "cg_replied": (
        "They replied, but you are not satisfied, so you can escalate.",
        "उन्होंने जवाब दिया, लेकिन आप संतुष्ट नहीं हैं, इसलिए आप आगे शिकायत कर सकते हैं।"),
    "cg_done": (
        "You said their reply resolved the problem.",
        "आपने बताया कि उनके जवाब से समस्या हल हो गई।"),
    "rbi_await": (
        "The RBI Ombudsman only takes complaints after you have complained to the bank or app first.",
        "आरबीआई लोकपाल तभी शिकायत लेता है जब आप पहले बैंक या ऐप से शिकायत कर चुके हों।"),
    "rbi_locked": (
        "If they do not resolve it by {opens}, you can file with the RBI Ombudsman on or before {closes}.",
        "अगर {opens_hi} तक समस्या हल नहीं होती, तो आप {closes_hi} तक आरबीआई लोकपाल के पास शिकायत कर सकते हैं।"),
    "rbi_open_no_reply": (
        "They did not reply within 30 days, so the Ombudsman can now hear the complaint. File on or before {closes}.",
        "उन्होंने 30 दिनों में जवाब नहीं दिया, इसलिए अब लोकपाल शिकायत सुन सकता है। {closes_hi} तक शिकायत दर्ज करें।"),
    "rbi_open_replied": (
        "You are not satisfied with their reply, so you can file with the Ombudsman on or before {closes}.",
        "आप उनके जवाब से संतुष्ट नहीं हैं, इसलिए आप {closes_hi} तक लोकपाल के पास शिकायत कर सकते हैं।"),
    "rbi_open_reply_date_unknown": (
        "You are not satisfied with their reply, so you can file now. Add the reply date to see the last day to file.",
        "आप उनके जवाब से संतुष्ट नहीं हैं, इसलिए अभी शिकायत कर सकते हैं। आख़िरी तारीख़ जानने के लिए जवाब की तारीख़ बताएँ।"),
    "rbi_date_unknown": (
        "You can file 30 days after the bank receives your complaint. Add the complaint date to calculate it.",
        "बैंक को शिकायत मिलने के 30 दिन बाद आप लोकपाल के पास जा सकते हैं। तारीख़ बताएँ ताकि गणना हो सके।"),
    "rbi_expired": (
        "The filing window appears to have closed on {closes}. Check the official portal for your options.",
        "शिकायत दर्ज करने की अवधि {closes_hi} को ख़त्म होती दिख रही है। अपने विकल्पों के लिए आधिकारिक पोर्टल देखें।"),
    "rbi_window_unclear": (
        "You can file now. The official text was unclear about the last day, so please check the portal.",
        "आप अभी शिकायत कर सकते हैं। आख़िरी तारीख़ आधिकारिक पाठ में साफ़ नहीं थी, कृपया पोर्टल पर जाँचें।"),
    "rbi_skipped": (
        "Not needed: your complaint was resolved by the bank or app.",
        "ज़रूरत नहीं: बैंक या ऐप ने आपकी शिकायत हल कर दी।"),
    "nch_await": (
        "After you have complained to the company, you can register the complaint with the National Consumer Helpline.",
        "कंपनी से शिकायत करने के बाद आप राष्ट्रीय उपभोक्ता हेल्पलाइन पर शिकायत दर्ज कर सकते हैं।"),
    "nch_open": (
        "The company has not resolved it, so you can register with the National Consumer Helpline (toll-free 1915).",
        "कंपनी ने समस्या हल नहीं की, इसलिए आप राष्ट्रीय उपभोक्ता हेल्पलाइन (टोल-फ़्री 1915) पर शिकायत दर्ज कर सकते हैं।"),
    "nch_locked": (
        "You can register with the National Consumer Helpline from {opens}.",
        "आप {opens_hi} से राष्ट्रीय उपभोक्ता हेल्पलाइन पर शिकायत दर्ज कर सकते हैं।"),
    "nch_skipped": (
        "Not needed: your complaint was resolved by the company.",
        "ज़रूरत नहीं: कंपनी ने आपकी शिकायत हल कर दी।"),
    "commission_locked": (
        "If the helpline does not resolve it, you can approach the consumer commission. Check the time limit on the official site.",
        "अगर हेल्पलाइन से हल नहीं निकलता, तो आप उपभोक्ता आयोग जा सकते हैं। समय-सीमा आधिकारिक साइट पर जाँचें।"),
    "commission_skipped": (
        "Not needed: your complaint was resolved.",
        "ज़रूरत नहीं: आपकी शिकायत हल हो गई।"),
    "user_submitted_waiting": (
        "You filed this on {submitted} (acknowledgement {ack}). We will track the status.",
        "आपने इसे {submitted_hi} को दर्ज किया (पावती {ack})। हम इसकी स्थिति पर नज़र रखेंगे।"),
}

OPENS_WHEN = {
    "rbi_await": ("30 days after the bank or app receives your complaint (earlier if they reject it or you are "
                  "not satisfied with their reply)"),
    "rbi_date_unknown": "30 days after the bank received your complaint (add the complaint date to calculate it)",
    "rbi_open_reply_date_unknown": "Now: they replied and you are not satisfied",
    "nch_await": "After you have complained to the company",
    "nch_open": "Now (the waiting period before the helpline is not verified yet)",
    "commission_locked": "If the National Consumer Helpline does not resolve your complaint",
}

TIMELINE = {
    "case_created": ("Case created", "मामला बनाया गया"),
    "answers_saved": ("Details updated", "जानकारी अपडेट की गई"),
    "plan_ready": ("Escalation plan ready", "शिकायत की योजना तैयार"),
    "draft_ready": ("Draft ready for step {n}", "चरण {n} का मसौदा तैयार"),
    "draft_edited": ("You edited the draft for step {n}", "आपने चरण {n} का मसौदा बदला"),
    "route_found": ("Grievance contact found", "शिकायत संपर्क मिला"),
    "run_started": ("Agent started filling step {n}", "एजेंट ने चरण {n} भरना शुरू किया"),
    "review_ready": ("Form filled, stopped before Submit", "फ़ॉर्म भरा गया, सबमिट से पहले रुका"),
    "blocked": ("Portal needs you to continue by hand", "पोर्टल पर आगे आपको ख़ुद भरना होगा"),
    "safety_flagged": ("Safety check flagged the agent run", "सुरक्षा जाँच ने एजेंट रन को चिह्नित किया"),
    "run_failed": ("Agent run failed", "एजेंट रन विफल हुआ"),
    "run_cancelled": ("Agent run cancelled", "एजेंट रन रद्द किया गया"),
    "submitted": ("You submitted step {n}", "आपने चरण {n} जमा किया"),
    "status_checked": ("Status checked: {status}", "स्थिति जाँची गई: {status}"),
    "step_due": ("Waiting period over for step {n}", "चरण {n} की प्रतीक्षा अवधि पूरी"),
    "escalation_ready": ("Next filing prepared", "अगली शिकायत तैयार"),
    "closed": ("Case closed ({reason})", "मामला बंद ({reason})"),
    "rule_changed": ("Official rule changed", "आधिकारिक नियम बदला"),
}

BLOCKER_MESSAGE = ("This portal needs you to verify yourself. Open it here and continue, then come back with "
                   "your acknowledgement number.")

WARN = {
    "out_of_scope": "Sector-specific regulator steps are not covered yet; showing the general consumer route.",
    "stale_rule": "Rule not freshly verified; using stored copy from {date}.",
    "pre_2026": "Complaints made before 1 July 2026 may fall under the 2021 scheme. Please verify the deadline.",
    "seven_days": "Less than 7 days left to file with {forum} (last day {closes}).",
    "expired": ("The filing window for {forum} appears to have passed ({closes}). You can still write to the "
                "bank's Principal Nodal Officer; check the official portal for other options."),
    "satisfied": "You said you are satisfied with the reply, so no escalation is needed. You can close the case.",
    "nch_unverified": "The waiting period before the National Consumer Helpline is not verified yet; check the official site.",
    "commission_unverified": "The consumer commission time limit is not verified from official text yet; check e-Jagriti.",
}


def why(reason: str, ctx: dict[str, Any]) -> tuple[str, str]:
    en, hi = WHY.get(reason, ("", ""))
    full = dict(ctx)
    for k in ("complained", "due", "opens", "closes", "submitted"):
        if k in ctx and ctx[k] is not None:
            full[f"{k}_hi"] = fmt_date(ctx[k], "hi")
            full[k] = fmt_date(ctx[k], "en")
    full.setdefault("company", "the company")
    full.setdefault("company_hi", full["company"] if full["company"] != "the company" else "कंपनी")
    full.setdefault("ack", "-")
    try:
        return en.format(**full), hi.format(**full)
    except (KeyError, IndexError):
        return en, hi


def action(forum_id: str, company: str | None) -> tuple[str, str]:
    en, hi = ACTIONS.get(forum_id, ("Next step", "अगला कदम"))
    c = company or "the company"
    c_hi = company or "कंपनी"
    return en.format(company=c), hi.format(company_hi=c_hi)


def timeline_title(key: str, **kw: Any) -> tuple[str, str]:
    en, hi = TIMELINE.get(key, (key, key))
    return en.format(**kw), hi.format(**kw)
