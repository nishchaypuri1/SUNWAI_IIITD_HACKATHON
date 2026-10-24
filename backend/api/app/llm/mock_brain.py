"""Deterministic stand-in for the LLMs when MOCK_MODE=1 and no recorded fixture matches.

It goes through the same gateway path and returns schema-valid JSON, so the whole app works offline.
Extraction is heuristic (English / Hinglish / Hindi keywords, dates, amounts, known companies) and never
invents facts: anything it cannot find is null.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from dateutil import parser as dparser

from ..core import i18n, pii, safety

# ---------------------------------------------------------------- P1 intake
COUNTERPARTIES: list[tuple[str, str, str]] = [
    (r"amazon\s*pay", "Amazon Pay", "payment_app"),
    (r"hdfc\s*ergo", "HDFC ERGO", "insurer"),
    (r"icici\s*lombard", "ICICI Lombard", "insurer"),
    (r"bajaj\s*allianz", "Bajaj Allianz", "insurer"),
    (r"star\s*health", "Star Health", "insurer"),
    (r"\blic\b", "LIC", "insurer"),
    (r"phone\s*pe|फोनपे|फ़ोनपे", "PhonePe", "payment_app"),
    (r"paytm|पेटीएम", "Paytm", "payment_app"),
    (r"google\s*pay|\bgpay\b|\bg\s*pay\b", "Google Pay", "payment_app"),
    (r"\bbhim\b", "BHIM UPI", "payment_app"),
    (r"mobikwik", "MobiKwik", "payment_app"),
    (r"\bcred\b", "CRED", "payment_app"),
    (r"\bsbi\b|state bank|एसबीआई|स्टेट बैंक", "SBI", "bank"),
    (r"\bhdfc\b", "HDFC Bank", "bank"),
    (r"\bicici\b", "ICICI Bank", "bank"),
    (r"\baxis\b", "Axis Bank", "bank"),
    (r"\bkotak\b", "Kotak Mahindra Bank", "bank"),
    (r"\bpnb\b|punjab national", "Punjab National Bank", "bank"),
    (r"bank of baroda|\bbob\b", "Bank of Baroda", "bank"),
    (r"\bcanara\b", "Canara Bank", "bank"),
    (r"union bank", "Union Bank of India", "bank"),
    (r"yes\s*bank", "Yes Bank", "bank"),
    (r"indusind", "IndusInd Bank", "bank"),
    (r"\bidfc\b", "IDFC FIRST Bank", "bank"),
    (r"\bamazon\b|अमेज़न|अमेजन", "Amazon", "merchant"),
    (r"flipkart|फ्लिपकार्ट", "Flipkart", "merchant"),
    (r"myntra", "Myntra", "merchant"),
    (r"meesho", "Meesho", "merchant"),
    (r"\bajio\b", "AJIO", "merchant"),
    (r"nykaa", "Nykaa", "merchant"),
    (r"swiggy", "Swiggy", "merchant"),
    (r"zomato", "Zomato", "merchant"),
    (r"blinkit", "Blinkit", "merchant"),
    (r"zepto", "Zepto", "merchant"),
    (r"bigbasket", "BigBasket", "merchant"),
    (r"croma", "Croma", "merchant"),
    (r"makemytrip|\bmmt\b", "MakeMyTrip", "merchant"),
    (r"goibibo", "Goibibo", "merchant"),
    (r"cleartrip", "Cleartrip", "merchant"),
    (r"\birctc\b", "IRCTC", "merchant"),
    (r"indigo|इंडिगो", "IndiGo", "airline"),
    (r"air\s*india|एयर इंडिया", "Air India", "airline"),
    (r"spicejet", "SpiceJet", "airline"),
    (r"akasa", "Akasa Air", "airline"),
    (r"\bjio\b|जियो", "Jio", "telco"),
    (r"airtel|एयरटेल", "Airtel", "telco"),
    (r"vodafone|\bvi\s+(?:sim|network|recharge)", "Vi", "telco"),
    (r"\bbsnl\b", "BSNL", "telco"),
]
TRAVEL_MERCHANTS = {"MakeMyTrip", "Goibibo", "Cleartrip", "IRCTC"}

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    "जनवरी": 1, "फ़रवरी": 2, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8,
    "सितंबर": 9, "सितम्बर": 9, "अक्टूबर": 10, "अक्तूबर": 10, "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
}
_EN_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_HI_MON = "(" + "|".join(k for k in MONTHS if not k.isascii()) + ")"
DATE_PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")),
    ("dmy", re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b")),
    ("d_mon", re.compile(rf"(?i)\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?{_EN_MON}\b\.?,?(?:\s+(\d{{4}}))?")),
    ("mon_d", re.compile(rf"(?i)\b{_EN_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?")),
    ("d_mon_hi", re.compile(rf"(\d{{1,2}})\s*{_HI_MON}(?:\s*,?\s*(\d{{4}}))?")),
]
COMPLAINT_KW = ["complained", "complaint", "complain", "shikayat", "शिकायत", "raised", "ticket", "lodged",
                "registered", "reported", "emailed", "wrote", "customer care", "contacted", "grievance"]
REPLY_KW = ["replied", "reply", "responded", "response", "jawab", "जवाब", "rejected", "reject", "closed my"]
INCIDENT_KW = ["debited", "deducted", "kaat", "kat ", "kate", "कट", "failed", "withdrawal", "transaction", "txn",
               "charged", "charge", "paid", "payment", "ordered", "order", "delivered", "picked up", "pickup",
               "cancel", "booked", "happened", "double", "twice", "baar", "लेनदेन", "flight", "udaan", "उड़ान",
               "returned", "return"]
HINGLISH_MARKERS = ["ne ", " ko ", " ki ", " kiya", "kaat", " nahi", " hai", "mera", "meri", "maine", "paise",
                    "jawab", " liye", " abhi", " tak ", " se ", " kar ", " thi", " tha", "wapas", "chahiye", "baar"]
_BOUNDARY = re.compile(r"[.!?।;\n]|,(?!\d)")


def _resolve_year(day: int, month: int, year: int | None, today: date) -> date | None:
    try:
        if year is not None:
            if year < 100:
                year += 2000
            return date(year, month, day)
        d = date(today.year, month, day)
        if d > today:
            d = date(today.year - 1, month, day)
        return d
    except ValueError:
        return None


def find_dates(text: str, today: date) -> list[tuple[int, int, date]]:
    found: list[tuple[int, int, date]] = []
    taken: list[tuple[int, int]] = []
    for kind, pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span()
            if any(not (e <= a or s >= b) for a, b in taken):
                continue
            g = m.groups()
            d: date | None = None
            if kind == "iso":
                d = _resolve_year(int(g[2]), int(g[1]), int(g[0]), today)
            elif kind == "dmy":
                d = _resolve_year(int(g[0]), int(g[1]), int(g[2]), today)
            elif kind in ("d_mon", "d_mon_hi"):
                d = _resolve_year(int(g[0]), MONTHS[g[1].lower()], int(g[2]) if g[2] else None, today)
            elif kind == "mon_d":
                d = _resolve_year(int(g[1]), MONTHS[g[0].lower()], int(g[2]) if g[2] else None, today)
            if d:
                found.append((s, e, d))
                taken.append((s, e))
    low = text.lower()
    for m in re.finditer(r"\b(yesterday|today|aaj)\b|आज|कल रात", low):
        word = m.group(0)
        d = today - timedelta(days=1) if word in ("yesterday",) else today
        found.append((m.start(), m.end(), d))
    return sorted(found)


def _clause(text: str, s: int, e: int) -> tuple[int, int]:
    start = 0
    for m in _BOUNDARY.finditer(text, 0, s):
        start = m.end()
    m2 = _BOUNDARY.search(text, e)
    end = m2.start() if m2 else len(text)
    return start, end


def _classify_date(text: str, s: int, e: int) -> str:
    cs, ce = _clause(text, s, e)
    clause = text[cs:ce].lower()
    best, best_d = "incident", 10 ** 6
    for cat, kws in (("complaint", COMPLAINT_KW), ("reply", REPLY_KW), ("incident", INCIDENT_KW)):
        for kw in kws:
            for m in re.finditer(re.escape(kw), clause):
                ks, ke = m.start() + cs, m.end() + cs
                if ke <= s:
                    dist = s - ke
                elif ks >= e:
                    dist = ks - e + 2   # slight preference for keywords that come before the date
                else:
                    continue
                if dist < best_d:
                    best, best_d = cat, dist
    return best


def _amount(text: str) -> float | None:
    pats = [
        r"(?i)(?:₹|rs\.?|inr|rupees?)\s*([\d,]+(?:\.\d{1,2})?)",
        r"(?i)([\d,]+(?:\.\d{1,2})?)\s*(?:₹|rs\b|rupees?|rupaye|rupay|रुपये|रुपए|रु\.?)",
        r"(?<![\d,/.-])(\d{1,3}(?:,\d{2,3})+)(?![\d,/-])",
        r"(?i)(?<![\d,/.-])(\d{2,7})\s+(?:do baar |twice |)(?:kaat|kat|debit|deduct|charged|कट)",
    ]
    for p in pats:
        m = re.search(p, text)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if 0 < v < 1e8:
                return v
    return None


def _has(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def extract_case(text: str, today: date, language_hint: str | None = None, image_count: int = 0) -> dict:
    low = text.lower()
    # language
    deva = sum(1 for ch in text if "ऀ" <= ch <= "ॿ")
    letters = sum(1 for ch in text if ch.isalpha()) or 1
    if language_hint in ("en", "hi", "hinglish"):
        language = language_hint
    elif deva / letters > 0.3:
        language = "hi"
    elif sum(1 for mk in HINGLISH_MARKERS if mk in f" {low} ") >= 2:
        language = "hinglish"
    else:
        language = "en"

    # counterparty
    cp_name, cp_type = None, None
    for pat, name, typ in COUNTERPARTIES:
        if re.search(pat, low):
            cp_name, cp_type = name, typ
            break
    if cp_name is None:
        m = re.search(r"\b([A-Z][A-Za-z&]+(?:\s[A-Z][A-Za-z&]+)?)\s+Bank\b", text)
        if m:
            cp_name, cp_type = f"{m.group(1)} Bank", "bank"

    # category
    if cp_type in ("bank", "payment_app"):
        category = "bank_payment"
    elif cp_type == "airline" or cp_name in TRAVEL_MERCHANTS:
        category = "travel"
    elif cp_type == "merchant":
        category = "ecommerce_refund"
    elif cp_type == "telco":
        category = "telecom"
    elif cp_type == "insurer":
        category = "insurance"
    elif _has(low, [r"\bupi\b", r"\batm\b", r"debit", r"kaat", r"\bcard\b", r"account", r"लेनदेन", r"खाते"]):
        category = "bank_payment"
    elif _has(low, [r"flight", r"train", r"hotel", r"booking", r"उड़ान"]):
        category = "travel"
    elif _has(low, [r"order", r"delivery", r"return", r"product"]):
        category = "ecommerce_refund"
    elif _has(low, [r"recharge", r"\bsim\b", r"network", r"broadband"]):
        category = "telecom"
    elif _has(low, [r"policy", r"claim", r"insurance"]):
        category = "insurance"
    else:
        category = "other"

    # prior contact
    negated_contact = _has(low, [
        r"(complaint|complain|shikayat|शिकायत)\s+(abhi tak\s+)?(nahi|nahin|नहीं|not)\b",
        r"(not yet|haven't|have not|didn't|did not|never)\s+(yet\s+)?(complain|raised|contacted|filed|lodged|reported)",
        r"no complaint (yet|so far)", r"शिकायत नहीं",
    ])
    positive_contact = _has(low, [
        r"\bcomplained\b", r"complaint (ki|kiya|di|dee|kari|darj)", r"(raised|filed|registered|lodged|logged) (a |my )?complaint",
        r"shikayat (ki|kiya|di)", r"शिकायत (की|दर्ज)", r"customer care (ko|se)", r"contacted (the )?(bank|customer care|support)",
        r"(wrote|emailed|mailed) (to )?(the )?(bank|company|support)", r"complaint (number|no\.?|id)", r"\bticket\b",
        r"rejected my complaint", r"my complaint",
    ])
    contacted: bool | None = None
    if negated_contact:
        contacted = False
    elif positive_contact:
        contacted = True

    got_reply: bool | None = None
    if _has(low, [r"no (reply|response|update)", r"not (yet )?(replied|responded)", r"(haven't|have not|didn't|did not) "
                  r"(reply|respond|hear)", r"(koi )?jawab nahi", r"reply nahi", r"कोई जवाब नहीं", r"जवाब नहीं",
                  r"not heard back"]):
        got_reply = False
    elif _has(low, [r"\breplied\b", r"jawab (aaya|diya|mila)", r"reply (aaya|mila|di)", r"\bresponded\b",
                    r"\brejected\b", r"reject kar", r"mana kar", r"जवाब (दिया|आया|मिला)", r"closed my complaint"]):
        got_reply = True
    satisfied: bool | None = None
    if _has(low, [r"not satisfied", r"unsatisfied", r"dissatisfied", r"santusht nahi", r"संतुष्ट नहीं", r"\brejected\b",
                  r"reject kar", r"mana kar", r"not resolved", r"unresolved", r"\buseless\b", r"bekaar"]):
        satisfied = False
    elif _has(low, [r"satisfied with (the )?(reply|response|resolution)", r"(problem|issue) (is )?(solved|resolved)",
                    r"resolved my", r"santusht hoon", r"संतुष्ट हूँ", r"refunded the money"]):
        satisfied = True
    # dates
    incident = complaint_date = reply_date = None
    for s, e, d in find_dates(text, today):
        cat = _classify_date(text, s, e)
        if cat == "complaint" and complaint_date is None:
            complaint_date = d
        elif cat == "reply" and reply_date is None:
            reply_date = d
        elif cat == "incident" and incident is None:
            incident = d
    if complaint_date and contacted is None:
        contacted = True
    if reply_date and got_reply is None:
        got_reply = True
    if got_reply is not True:
        satisfied = None
    if contacted is not True:
        got_reply, satisfied = None, None

    # numbers
    m = re.search(r"(?i)(?:complaint|ticket|shikayat|शिकायत|service request|\bsr\b|case)\s*(?:no\.?|number|num|id|#|संख्या)\s*"
                  r"[:#-]?\s*([A-Z0-9][A-Z0-9-]{4,})", text)
    complaint_number = m.group(1) if m and re.search(r"\d", m.group(1)) else None
    refs: list[str] = []
    for m in re.finditer(r"(?i)\b(?:utr|txn(?:\s*id)?|transaction\s*(?:id|ref(?:erence)?|no\.?)|rrn|order(?:\s*(?:id|no\.?|number))?|"
                         r"pnr|booking\s*(?:id|ref)|ref(?:erence)?(?:\s*(?:no\.?|number))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{5,})", text):
        val = m.group(1)
        if re.search(r"\d", val) and val != complaint_number and val not in refs:
            refs.append(val)

    outcome = None
    if _has(low, [r"refund", r"wapas", r"वापस", r"money back", r"return my money", r"paise"]):
        outcome = "refund"
    elif _has(low, [r"reverse", r"reversal", r"do baar", r"twice", r"double"]):
        outcome = "reversal"
    elif _has(low, [r"replace"]):
        outcome = "replacement"

    evidence = []
    if image_count:
        evidence.append("screenshot attached")
    if _has(low, [r"screenshot", r"\bsms\b", r"statement", r"receipt", r"invoice"]):
        evidence.append("user mentions documentary proof (screenshot / SMS / statement)")

    words = text.split()
    summary = " ".join(words[:40])
    return {
        "language": language, "category": category, "summary": summary, "amount_inr": _amount(text),
        "incident_date": incident.isoformat() if incident else None,
        "counterparty": {"name": cp_name, "type": cp_type},
        "reference_numbers": refs,
        "prior_contact": {
            "contacted_company": contacted,
            "date": complaint_date.isoformat() if complaint_date else None,
            "complaint_number": complaint_number,
            "got_reply": got_reply,
            "reply_date": reply_date.isoformat() if reply_date else None,
            "satisfied_with_reply": satisfied,
        },
        "desired_outcome": outcome, "evidence_found": evidence, "missing_fields": [], "pii_flags": [],
    }


# ---------------------------------------------------------------- P2 rule extraction
def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def extract_rule(official_text: str, forum_id: str) -> dict:
    out: dict[str, Any] = {
        "scheme_name": None, "effective_from": None, "wait_days_before_escalation": None,
        "filing_window_days": None, "filing_window_counts_from": "unclear",
        "evidence": {"wait_days_before_escalation": None, "filing_window_days": None,
                     "filing_window_counts_from": None, "effective_from": None},
        "eligibility_conditions": [], "exclusions": [], "documents_required": [], "unknowns": [],
        "superseded_value_note": None, "confidence": "medium",
    }
    sents = _sentences(official_text)
    m = re.search(r"(Reserve Bank\s*[-–]\s*Integrated Ombudsman Scheme,?\s*20\d\d)", official_text)
    if m:
        out["scheme_name"] = m.group(1)
    for s in sents:
        low = s.lower()
        w = re.search(r"within (\d+) days", low)
        if out["filing_window_days"] is None and w and ("whichever is later" in low or "must be made" in low
                                                       or "can be filed" in low and "ombudsman" in low and "from" in low):
            out["filing_window_days"] = int(w.group(1))
            out["evidence"]["filing_window_days"] = s
            if "whichever is later" in low:
                out["filing_window_counts_from"] = "later_of_wait_end_or_last_reply"
                out["evidence"]["filing_window_counts_from"] = s
            continue
        r = re.search(r"(\d+) days", low)
        if out["wait_days_before_escalation"] is None and r and (
                "not received any reply" in low or "no reply" in low or "receipt of the complaint" in low):
            out["wait_days_before_escalation"] = int(r.group(1))
            out["evidence"]["wait_days_before_escalation"] = s
        if "must first approach" in low or "first approach" in low:
            out["eligibility_conditions"].append(s)
        eff = re.search(r"(?:with effect from|in force from|effective from)\s+([A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2} [A-Z][a-z]+,? \d{4})", s)
        if out["effective_from"] is None and eff:
            try:
                out["effective_from"] = dparser.parse(eff.group(1)).date().isoformat()
                out["evidence"]["effective_from"] = s
            except (ValueError, OverflowError):
                pass
    for k in ("wait_days_before_escalation", "filing_window_days", "effective_from"):
        if out[k] is None:
            out["unknowns"].append(k)
    if out["filing_window_counts_from"] == "unclear":
        out["unknowns"].append("filing_window_counts_from")
    return out


# ---------------------------------------------------------------- P4 drafts
def _issue_phrase(cj: dict, lang: str) -> str:
    amt = cj.get("amount_inr")
    amt_s = f"₹{amt:,.0f}" if amt else ("[please fill: amount]" if lang == "en" else "[please fill: राशि]")
    cp = (cj.get("counterparty") or {}).get("name") or "[please fill: company name]"
    d = cj.get("incident_date")
    d_s = i18n.fmt_date(d, lang) if d else ("[please fill: date]" if lang == "en" else "[please fill: तारीख़]")
    cat = cj.get("category")
    summary = (cj.get("summary") or "").lower()
    twice = any(k in summary for k in ("do baar", "twice", "double", "दो बार"))
    failed = any(k in summary for k in ("fail", "विफल"))
    if lang == "hi":
        if cat == "bank_payment":
            base = f"{d_s} को {cp} के माध्यम से {amt_s} की कटौती"
            if twice:
                base += " (राशि दो बार कटी)"
            if failed:
                base += ", जबकि लेनदेन विफल रहा"
            return base
        if cat == "travel":
            return f"{cp} से {amt_s} का रिफ़ंड, जो अभी तक नहीं मिला (घटना की तारीख़ {d_s})"
        return f"{cp} से {amt_s} का रिफ़ंड/समाधान, जो अभी तक नहीं मिला (तारीख़ {d_s})"
    if cat == "bank_payment":
        base = f"a debit of {amt_s} through {cp} on {d_s}"
        if twice:
            base = f"an amount of {amt_s} debited twice through {cp} on {d_s}"
        if failed:
            base += " for a transaction that failed"
        return base
    if cat == "travel":
        return f"a refund of {amt_s} from {cp} that I have not received (incident date {d_s})"
    if cat == "ecommerce_refund":
        return f"a refund of {amt_s} from {cp} that I have not received (date {d_s})"
    return f"an unresolved issue with {cp} involving {amt_s} (date {d_s})"


def draft(cj: dict, step: dict, lang: str, want_hindi: bool) -> dict:
    out = _draft_one(cj, step, "hi" if lang == "hi" else "en")
    if want_hindi and lang != "hi":
        h = _draft_one(cj, step, "hi")
        out["subject_hi"], out["body_hi"] = h["subject"], h["body"]
    return out


def _draft_one(cj: dict, step: dict, lang: str) -> dict:
    forum = step.get("forum_id")
    cp = (cj.get("counterparty") or {}).get("name") or "[please fill: company name]"
    refs = ", ".join(cj.get("reference_numbers") or []) or "[please fill: transaction reference]"
    issue = _issue_phrase(cj, lang)
    outcome = cj.get("desired_outcome")
    prev_no = step.get("prev_complaint_number") or "[please fill: complaint number]"
    prev_date = step.get("prev_complaint_date")
    prev_d = i18n.fmt_date(prev_date, lang) if prev_date else "[please fill: complaint date]"
    attachments = ["Transaction proof (screenshot / SMS / statement)"]
    if lang == "hi":
        ask = {"refund": "कृपया राशि मेरे खाते में वापस करें।", "reversal": "कृपया ग़लत कटौती को वापस करें।",
               "replacement": "कृपया उत्पाद बदलें।"}.get(outcome or "", "कृपया इस समस्या का समाधान करें।")
        sign = "भवदीय,\n[please fill: आपका पूरा नाम]\n[please fill: पंजीकृत मोबाइल नंबर के आख़िरी 4 अंक]"
        if forum == "rbi_cms":
            wait = ("बैंक ने 30 दिनों में कोई जवाब नहीं दिया।" if step.get("wait_elapsed") else
                    (f"बैंक ने {i18n.fmt_date(step['reply_date'], 'hi')} को जवाब दिया, जिससे मेरी समस्या हल नहीं हुई।"
                     if step.get("reply_date") else "बैंक के जवाब से मेरी समस्या हल नहीं हुई।"))
            subject = f"{cp} के ख़िलाफ़ शिकायत: {issue[:60]}"
            body = (f"महोदय/महोदया,\n\nमैं {cp} के ख़िलाफ़ शिकायत दर्ज करना चाहता/चाहती हूँ। मामला: {issue}।\n"
                    f"संदर्भ: {refs}\n\nमैंने {prev_d} को {cp} से शिकायत की थी (शिकायत संख्या {prev_no})। {wait}\n\n"
                    f"{ask}\n\nसंलग्न: लेनदेन का प्रमाण, बैंक को की गई शिकायत की प्रति और बैंक का जवाब (यदि हो)।\n\n{sign}")
            attachments += ["बैंक को की गई शिकायत की प्रति", "बैंक का जवाब (यदि हो)"]
        elif forum == "nch":
            subject = f"{cp} के ख़िलाफ़ उपभोक्ता शिकायत"
            body = (f"महोदय/महोदया,\n\nमेरी शिकायत {cp} के ख़िलाफ़ है। मामला: {issue}।\nसंदर्भ: {refs}\n\n"
                    f"मैंने {prev_d} को कंपनी से शिकायत की थी (शिकायत संख्या {prev_no}), पर समस्या हल नहीं हुई।\n\n{ask}\n\n{sign}")
        else:
            subject = f"शिकायत: {issue[:70]}"
            body = (f"महोदय/महोदया,\n\nमैं {issue} के बारे में शिकायत दर्ज करना चाहता/चाहती हूँ।\nसंदर्भ: {refs}\n\n"
                    f"{ask}\n\nकृपया इस शिकायत की पावती और शिकायत संख्या दें।\n\n{sign}")
        return {"subject": subject, "body": body, "attachments_to_mention": attachments}

    ask = {"refund": "I request a refund of the amount to my account.",
           "reversal": "I request that the wrong debit be reversed.",
           "replacement": "I request a replacement."}.get(outcome or "", "I request that this issue be resolved.")
    sign = "Yours faithfully,\n[please fill: your full name]\n[please fill: last 4 digits of your registered mobile number]"
    if forum == "rbi_cms":
        if step.get("wait_elapsed"):
            wait = f"I did not receive a reply within 30 days of {cp} receiving my complaint."
        elif step.get("reply_date"):
            wait = (f"{cp} replied on {i18n.fmt_date(step['reply_date'])}, but the reply does not resolve my "
                    "complaint.")
        else:
            wait = f"The reply from {cp} does not resolve my complaint."
        subject = f"Complaint against {cp}: {issue[:70]}"
        body = (f"Dear Sir/Madam,\n\nI wish to file a complaint against {cp} regarding {issue}.\n"
                f"Reference: {refs}\n\nI first complained to {cp} on {prev_d} (complaint number {prev_no}). {wait}\n\n"
                f"{ask}\n\nAttached: proof of the transaction, a copy of my complaint to {cp}, and their reply "
                f"if any.\n\n{sign}")
        attachments += [f"Copy of complaint to {cp}", f"Reply from {cp} (if any)"]
    elif forum == "nch":
        subject = f"Consumer complaint against {cp}"
        body = (f"Dear Sir/Madam,\n\nI wish to register a consumer complaint against {cp} regarding {issue}.\n"
                f"Reference: {refs}\n\nI complained to {cp} on {prev_d} (complaint number {prev_no}), but the issue "
                f"has not been resolved.\n\n{ask}\n\n{sign}")
        attachments += [f"Copy of complaint to {cp}"]
    else:
        subject = f"Complaint: {issue[:80]}"
        body = (f"Dear Sir/Madam,\n\nI am writing to raise a complaint regarding {issue}.\nReference: {refs}\n\n"
                f"{ask}\n\nPlease acknowledge this complaint and share a complaint number.\n\n{sign}")
    return {"subject": subject, "body": body, "attachments_to_mention": attachments}


# ---------------------------------------------------------------- P5 field mapping
def map_fields(labels: list[str], cj: dict, draft_obj: dict | None, date_format: str) -> dict:
    def fmt(d: str | None) -> str | None:
        if not d:
            return None
        dd = date.fromisoformat(d)
        return dd.strftime("%d/%m/%Y") if date_format.upper().startswith("DD") else dd.isoformat()

    cat = cj.get("category")
    cp_type = (cj.get("counterparty") or {}).get("type")
    out = []
    for label in labels:
        low = label.lower()
        value, source = None, None
        if "category" in low or "type of complaint" in low:
            value = "UPI / payment" if (cp_type == "payment_app" or cat == "bank_payment") else "Other"
            source = "case_json.category"
        elif "previous complaint" in low or "earlier complaint" in low or "ticket" in low:
            value = (cj.get("prior_contact") or {}).get("complaint_number")
            source = "case_json.prior_contact.complaint_number" if value else None
        elif "date" in low:
            value = fmt(cj.get("incident_date"))
            source = "case_json.incident_date" if value else None
        elif "reference" in low or "utr" in low or "transaction id" in low or "order" in low:
            refs = cj.get("reference_numbers") or []
            value = refs[0] if refs else None
            source = "case_json.reference_numbers[0]" if value else None
        elif "amount" in low:
            amt = cj.get("amount_inr")
            value = (f"{amt:.2f}".rstrip("0").rstrip(".")) if amt else None
            source = "case_json.amount_inr" if value else None
        elif "description" in low or "details" in low or "complaint" in low or "message" in low:
            if draft_obj:
                value = draft_obj.get("body")
                source = "draft.body"
        elif "company" in low or "bank name" in low or "entity" in low:
            value = (cj.get("counterparty") or {}).get("name")
            source = "case_json.counterparty.name" if value else None
        # name, mobile, email, account: never stored by Sunwai -> left for the user
        out.append({"label": label, "value": value, "source": source})
    return {"field_map": out, "warnings": []}


# ---------------------------------------------------------------- P6 normalisers
_BLOCKERS = {"login", "otp", "captcha", "portal_down", "form_not_found", "bot_challenge"}


def normalize_fill(raw: Any) -> dict:
    r = raw if isinstance(raw, dict) else {}
    filled = []
    for f in r.get("fields_filled") or []:
        if isinstance(f, dict) and f.get("label"):
            filled.append({"label": str(f["label"]), "value": None if f.get("value") is None else str(f["value"])})
    blocker = r.get("blocker")
    blocker = blocker if blocker in _BLOCKERS else "none"
    return {
        "reached_review_screen": bool(r.get("reached_review_screen") is True),
        "page_url": r.get("page_url") or None,
        "fields_filled": filled,
        "fields_missing": [str(x) for x in (r.get("fields_missing") or [])],
        "blocker": blocker,
        "final_submit_clicked": bool(r.get("final_submit_clicked") is True),
        "notes": r.get("notes") or None,
    }


def normalize_status(raw: Any) -> dict:
    r = raw if isinstance(raw, dict) else {}
    text = str(r.get("status_text") or "")
    low = text.lower()
    if not r.get("found", bool(text)):
        norm = "unknown"
    elif any(k in low for k in ("reject", "not upheld", "declined")):
        norm = "rejected"
    elif any(k in low for k in ("replied", "response sent", "resolution provided", "reply sent", "resolved")):
        norm = "replied"
    elif "closed" in low:
        norm = "closed"
    elif any(k in low for k in ("progress", "review", "examination", "pending", "under process", "assigned")):
        norm = "in_progress"
    elif any(k in low for k in ("received", "registered", "submitted", "acknowledged")):
        norm = "received"
    else:
        norm = "unknown"
    blocker = r.get("blocker")
    last = r.get("last_updated") or None
    if last:
        try:
            last = dparser.parse(str(last), dayfirst=True).date().isoformat()
        except (ValueError, OverflowError):
            last = None
    return {"found": bool(r.get("found", bool(text))), "status_text": text or None, "normalized_status": norm,
            "last_updated": last, "remarks": r.get("remarks") or None,
            "blocker": blocker if blocker in _BLOCKERS else None}


# ---------------------------------------------------------------- P9 escalation
def escalation(engine: dict) -> dict:
    rec = engine.get("engine_recommendation") or "needs_user_input"
    nxt = engine.get("next_forum_name") or "the next forum"
    deadline = engine.get("next_closes_at")
    if rec == "escalate":
        reasoning = f"The waiting period is over without a resolution, so you can now file with {nxt}."
        if deadline:
            reasoning += f" File on or before {i18n.fmt_date(deadline)}."
    elif rec == "wait_more":
        reasoning = f"{nxt} opens on {i18n.fmt_date(engine.get('next_opens_at'))}. Wait until then."
    elif rec == "close":
        reasoning = "Your complaint appears resolved, so no further filing is needed."
    else:
        reasoning = "Some details are missing or the filing window may have passed. Please check the case details."
    checklist = list(engine.get("documents_required") or [])
    for a in engine.get("acks") or []:
        checklist.append(f"Acknowledgement / complaint number {a}")
    return {"recommendation": rec, "next_forum_id": engine.get("next_forum_id"), "filing_deadline": deadline,
            "reasoning": reasoning, "evidence_pack_checklist": checklist,
            "needs_verification": bool(engine.get("needs_verification"))}


# ---------------------------------------------------------------- dispatcher
def run(prompt_id: str, v: dict[str, Any]) -> dict:
    if prompt_id == "P1":
        today = date.fromisoformat(v["today"])
        return extract_case(v["text"], today, v.get("language_hint"), int(v.get("image_count", 0)))
    if prompt_id == "P2":
        return extract_rule(v["official_text"], v.get("forum_id", ""))
    if prompt_id == "P3":
        return {"steps": [{"ordinal": s["ordinal"], "why": s["template_why"], "why_hi": s["template_why_hi"]}
                          for s in v["steps"]], "order_check": []}
    if prompt_id == "P4":
        return draft(v["case"], v["step_context"], v.get("language", "en"), bool(v.get("want_hindi")))
    if prompt_id == "P5":
        return map_fields(v["labels"], v["case"], v.get("draft"), v.get("date_format", "DD/MM/YYYY"))
    if prompt_id == "P6_fill":
        return normalize_fill(v["raw"])
    if prompt_id == "P6_status":
        return normalize_status(v["raw"])
    if prompt_id == "P7":
        cj = v.get("case") or {}
        allow = [*(cj.get("reference_numbers") or []), (cj.get("prior_contact") or {}).get("complaint_number") or ""]
        issues = safety.check_draft_text(f"{v['subject']}\n{v['body']}", allow=[a for a in allow if a])
        return {"ok": not issues, "issues": issues}
    if prompt_id == "P9":
        return escalation(v["engine"])
    if prompt_id == "P8":
        return {}
    raise KeyError(prompt_id)


__all__ = ["run", "extract_case", "extract_rule", "find_dates", "pii"]
