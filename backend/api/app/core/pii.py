"""PII minimisation. Runs on all text before any LLM / TinyFish call and before saving.

Never kept: Aadhaar, PAN, full card or account numbers, passwords, OTPs, PINs, CVVs.
Numbers are reduced to their last 4 digits (XXXX1234). Transaction / order / complaint references that
are explicitly labelled as such (UTR, txn, order, ticket ...) are kept because the complaint needs them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_SECRET_DIGITS = re.compile(
    r"(?i)\b(otp|one[- ]time password|upi pin|mpin|pin|cvv|cvc|passcode)\b(\s*(?:is|was|hai|tha|:|=|-|number|no\.?)?\s*)(\d{3,8})\b"
)
_PASSWORD = re.compile(r"(?i)\b(password|passwd|pwd)\b(\s*(?:is|was|hai|:|=)\s*)(\S{3,})")
_PAN = re.compile(r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b")
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)@([A-Za-z0-9-]+\.[A-Za-z0-9.-]+)\b")
_DIGITS = re.compile(r"(?<![\w/.,₹])(\+91[ -]?)?(\d(?:[ -]?\d){6,22})(?![\w/])(?![.,]\d)")

_CTX_ACCOUNT = re.compile(r"(?i)(a/?c|acct|account|khata|खाता|खाते)[\s\w.:#-]{0,14}$")
_CTX_CARD = re.compile(r"(?i)(card|कार्ड)[\s\w.:#-]{0,14}$")
_CTX_AADHAAR = re.compile(r"(?i)(aadhaa?r|adhar|आधार|uid)[\s\w.:#-]{0,14}$")
_CTX_PHONE = re.compile(r"(?i)(mobile|phone|contact|whatsapp|mob\.?|फ़ोन|फोन|मोबाइल)[\s\w.:#-]{0,14}$")
_CTX_REFERENCE = re.compile(
    r"(?i)(utr|txn|transaction|trxn|rrn|ref|reference|order|ticket|complaint|booking|pnr|upi|shikayat|"
    r"शिकायत|लेनदेन|सर्विस|service request|sr|case|awb|tracking|invoice|bill)[\s\w.:#-]{0,14}$"
)


@dataclass
class ScrubResult:
    text: str
    flags: list[str] = field(default_factory=list)


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def last4(digits: str) -> str:
    d = re.sub(r"\D", "", digits)
    return d[-4:] if len(d) >= 4 else d


def scrub(text: str | None, *, keep_references: bool = True) -> ScrubResult:
    if not text:
        return ScrubResult(text or "", [])
    flags: list[str] = []

    def flag(f: str) -> None:
        if f not in flags:
            flags.append(f)

    def secret(m: re.Match) -> str:
        flag("sensitive_data_in_input")
        return f"{m.group(1)}{m.group(2)}[removed]"

    out = _SECRET_DIGITS.sub(secret, text)
    out = _PASSWORD.sub(secret, out)

    def pan(m: re.Match) -> str:
        s = m.group(0)
        # PAN: 4th letter encodes holder type (P, C, H, F, A, T, B, L, J, G); require uppercase original
        if not s.isupper():
            return s
        flag("pan_removed")
        return "[PAN removed]"

    out = _PAN.sub(pan, out)

    def email(m: re.Match) -> str:
        flag("email_masked")
        return f"{m.group(1)}***@{m.group(3)}"

    out = _EMAIL.sub(email, out)

    def digits(m: re.Match) -> str:
        prefix, raw = m.group(1) or "", m.group(2)
        d = re.sub(r"\D", "", raw)
        n = len(d)
        before = out_src[max(0, m.start() - 40):m.start()]
        if _CTX_ACCOUNT.search(before):
            flag("account_number_masked")
            return "XXXX" + d[-4:]
        if _CTX_CARD.search(before) and n >= 12:
            flag("card_number_masked")
            return "XXXX" + d[-4:]
        if _CTX_AADHAAR.search(before) and n == 12:
            flag("aadhaar_masked")
            return "XXXX XXXX " + d[-4:]
        if _CTX_PHONE.search(before) or (n == 10 and d[0] in "6789") or (prefix and n == 10):
            if n == 10:
                flag("phone_masked")
                return "XXXXXX" + d[-4:]
        if keep_references and _CTX_REFERENCE.search(before):
            return m.group(0)
        if n < 9:
            return m.group(0)
        if n == 12:
            flag("aadhaar_masked")
            return "XXXX XXXX " + d[-4:]
        if 13 <= n <= 19 and _luhn_ok(d):
            flag("card_number_masked")
            return "XXXX" + d[-4:]
        flag("account_number_masked")
        return "XXXX" + d[-4:]

    out_src = out
    out = _DIGITS.sub(digits, out)
    return ScrubResult(out, flags)


def scrub_reference(v: str | None) -> str | None:
    """Scrub a value that is known to be a transaction / order / complaint reference (kept, minus secrets)."""
    if v is None:
        return None
    prefix = "Reference: "
    return scrub(prefix + v).text[len(prefix):]


def scrub_value(v: str | None) -> str | None:
    if v is None:
        return None
    return scrub(v).text


_RAW_PATTERNS = [
    re.compile(r"(?<![\dX])\d{4}\s?\d{4}\s?\d{4}(?!\d)"),      # Aadhaar-like 12 digits
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),                   # PAN
    re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),            # card-like
]


def find_raw_pii(text: str, allow: list[str] | None = None) -> list[str]:
    """Used by tests and eval: return raw PII-looking substrings still present in text."""
    hits = []
    for p in _RAW_PATTERNS:
        for m in p.finditer(text or ""):
            s = m.group(0)
            if allow and any(re.sub(r'\D', '', s) == re.sub(r'\D', '', a) for a in allow):
                continue
            hits.append(s)
    return hits
