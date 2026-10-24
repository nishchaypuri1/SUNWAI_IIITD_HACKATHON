"""Intake (E7) and answers (E8): PII scrub -> P1 -> post-process -> missing fields -> questions."""
from __future__ import annotations

import base64
import io
import logging
import re
from datetime import date
from typing import Any

from PIL import Image, UnidentifiedImageError

from .. import clock, repo, schemas
from ..core import i18n, pii
from ..core.ladder import OUT_OF_SCOPE
from ..errors import ApiError, illegal, validation_error
from ..events import bus
from ..llm.gateway import gateway
from ..llm.mock_brain import COUNTERPARTIES

log = logging.getLogger("sunwai.intake")

ALLOWED_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
MAX_BYTES = 5 * 1024 * 1024
MAX_FILES = 3

ANSWERABLE: dict[str, str] = {
    "counterparty.name": "text", "counterparty.type": "select", "category": "select", "incident_date": "date",
    "amount_inr": "number", "desired_outcome": "select", "prior_contact.contacted_company": "boolean",
    "prior_contact.date": "date", "prior_contact.complaint_number": "text", "prior_contact.got_reply": "boolean",
    "prior_contact.reply_date": "date", "prior_contact.satisfied_with_reply": "boolean",
}
ENUMS = {
    "counterparty.type": {"bank", "payment_app", "merchant", "airline", "telco", "insurer", "other"},
    "category": {"bank_payment", "ecommerce_refund", "travel", "telecom", "insurance", "other"},
    "desired_outcome": {"refund", "reversal", "replacement", "apology", "other"},
}


# ------------------------------------------------------------ files
def process_image(content_type: str | None, data: bytes, filename: str = "") -> str:
    if len(data) > MAX_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", f"{filename or 'File'} is larger than 5 MB.")
    ctype = (content_type or "").lower()
    if ctype not in ALLOWED_TYPES:
        raise ApiError(415, "UNSUPPORTED_FILE", f"{filename or 'File'} must be a JPEG, PNG or WebP image.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ApiError(415, "UNSUPPORTED_FILE", f"{filename or 'File'} is not a readable image.")
    if img.format not in ("JPEG", "PNG", "WEBP"):
        raise ApiError(415, "UNSUPPORTED_FILE", f"{filename or 'File'} must be a JPEG, PNG or WebP image.")
    if img.width > 1600:
        img = img.resize((1600, int(img.height * 1600 / img.width)))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ------------------------------------------------------------ helpers
def _get(cj: dict, path: str) -> Any:
    cur: Any = cj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set(cj: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = cj
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _valid_date(v: Any) -> str | None:
    d = clock.parse_date(v) if isinstance(v, str) else None
    return d.isoformat() if d else None


def normalize_case_json(raw: dict, language_override: str | None, pii_flags: list[str], image_count: int) -> dict:
    cj = schemas.CaseJson.model_validate(_coerce(raw)).model_dump()
    if language_override in ("en", "hi", "hinglish"):
        cj["language"] = language_override
    for k in ("incident_date",):
        cj[k] = _valid_date(cj.get(k))
    pc = cj["prior_contact"]
    pc["date"], pc["reply_date"] = _valid_date(pc.get("date")), _valid_date(pc.get("reply_date"))
    # defence in depth: mask again whatever came back from the model
    cj["summary"] = pii.scrub(" ".join((cj.get("summary") or "").split()[:40])).text
    cj["reference_numbers"] = [pii.scrub_reference(r) for r in cj.get("reference_numbers") or []][:10]
    if pc.get("complaint_number"):
        pc["complaint_number"] = (pii.scrub_reference(pc["complaint_number"]) or "")[:64]
    cp = cj["counterparty"]
    if cp.get("name"):
        cp["name"] = pii.scrub(cp["name"]).text[:80]
    if pc.get("contacted_company") is not True:
        pc["got_reply"] = None if pc.get("contacted_company") is None else pc.get("got_reply")
    if pc.get("got_reply") is not True:
        pc["satisfied_with_reply"] = None if pc.get("got_reply") is None else pc.get("satisfied_with_reply")
    flags = list(dict.fromkeys([*(cj.get("pii_flags") or []), *pii_flags]))
    cj["pii_flags"] = flags
    ev = list(cj.get("evidence_found") or [])
    if image_count and "screenshot attached" not in ev:
        ev.append("screenshot attached")
    cj["evidence_found"] = ev
    return cj


def _coerce(raw: dict) -> dict:
    """Make obviously-wrong model output fit the contract instead of failing the whole intake."""
    out = dict(raw or {})
    for key, allowed, default in (("language", {"en", "hi", "hinglish"}, "en"),
                                  ("category", ENUMS["category"], "other")):
        if out.get(key) not in allowed:
            out[key] = default
    if out.get("desired_outcome") not in ENUMS["desired_outcome"]:
        out["desired_outcome"] = None
    cp = dict(out.get("counterparty") or {})
    if cp.get("type") not in ENUMS["counterparty.type"]:
        cp["type"] = None
    out["counterparty"] = cp
    try:
        out["amount_inr"] = float(out["amount_inr"]) if out.get("amount_inr") not in (None, "") else None
    except (TypeError, ValueError):
        out["amount_inr"] = None
    return out


def missing_fields(cj: dict) -> list[str]:
    pc = cj.get("prior_contact") or {}
    missing = []
    if not cj.get("incident_date"):
        missing.append("incident_date")
    if not (cj.get("counterparty") or {}).get("name"):
        missing.append("counterparty.name")
    if pc.get("contacted_company") is None:
        missing.append("prior_contact.contacted_company")
    elif pc.get("contacted_company") is True:
        if not pc.get("date"):
            missing.append("prior_contact.date")
        if pc.get("got_reply") is None:
            missing.append("prior_contact.got_reply")
        elif pc.get("got_reply") is True:
            if not pc.get("reply_date"):
                missing.append("prior_contact.reply_date")
            if pc.get("satisfied_with_reply") is None:
                missing.append("prior_contact.satisfied_with_reply")
    return missing


def contradictions(cj: dict, today: date) -> list[tuple[str, str]]:
    pc = cj.get("prior_contact") or {}
    inc, c, r = (clock.parse_date(cj.get("incident_date")), clock.parse_date(pc.get("date")),
                 clock.parse_date(pc.get("reply_date")))
    out = []
    for field, d in (("incident_date", inc), ("prior_contact.date", c), ("prior_contact.reply_date", r)):
        if d and d > today:
            out.append((field, f"The date for {field} is in the future. Please confirm it."))
    if inc and c and c < inc:
        out.append(("prior_contact.date", "The complaint date is before the incident date. Please confirm it."))
    if c and r and r < c:
        out.append(("prior_contact.reply_date", "The reply date is before the complaint date. Please confirm it."))
    return out


def build_questions(missing: list[str], contra: list[tuple[str, str]]) -> list[dict]:
    qs: list[dict] = []
    seen = set()
    for field, _ in contra:
        if field in seen or field not in i18n.QUESTIONS:
            continue
        base = i18n.QUESTIONS[field]
        qs.append({"field": field, "question": i18n.CONFIRM_PREFIX[0] + base["question"],
                   "question_hi": i18n.CONFIRM_PREFIX[1] + base["question_hi"], "input": base["input"],
                   **({"options": base["options"]} if base.get("options") else {})})
        seen.add(field)
    for field in i18n.QUESTION_ORDER:
        if field in missing and field not in seen:
            base = i18n.QUESTIONS[field]
            qs.append({"field": field, "question": base["question"], "question_hi": base["question_hi"],
                       "input": base["input"], **({"options": base["options"]} if base.get("options") else {})})
            seen.add(field)
    return qs[:4]


def refresh_derived(case: dict) -> None:
    cj = case["case_json"]
    miss = missing_fields(cj)
    cj["missing_fields"] = miss
    contra = contradictions(cj, clock.today())
    case["questions"] = build_questions(miss, contra)
    warnings = [w for _, w in contra]
    if cj.get("category") in OUT_OF_SCOPE:
        warnings.append(i18n.WARN["out_of_scope"])
    if "sensitive_data_in_input" in (cj.get("pii_flags") or []):
        warnings.append("We removed sensitive details (OTP, PIN or password) from your message. Never share them.")
    case.setdefault("meta", {})["intake_warnings"] = list(dict.fromkeys(warnings))
    case["warnings"] = list(case["meta"]["intake_warnings"])


# ------------------------------------------------------------ E7
async def create_case(text: str, language: str | None, images: list[str]) -> dict:
    scrubbed = pii.scrub(text)
    raw = await gateway().run("P1", {"text": scrubbed.text, "language_hint": language,
                                     "today": clock.today().isoformat(), "image_count": len(images)},
                              images=images or None, cacheable=not scrubbed.flags and not images)
    cj = normalize_case_json(raw, language, scrubbed.flags, len(images))
    now = clock.now_iso()
    case = {
        "id": repo.new_id("cs"), "created_at": now, "updated_at": now, "state": "INTAKE_DONE",
        "language": cj["language"], "text_masked": scrubbed.text, "case_json": cj, "questions": [],
        "warnings": [], "timeline": [], "meta": {},
    }
    refresh_derived(case)
    repo.add_timeline(case, "case_created")
    repo.insert_case(case)
    bus.publish(case["id"], "case_updated", {"state": case["state"]})
    return case


# ------------------------------------------------------------ E8
def _coerce_answer(field: str, value: Any) -> Any:
    kind = ANSWERABLE[field]
    if value is None:
        return None
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "yes", "y", "1", "haan", "ha", "हाँ"):
            return True
        if s in ("false", "no", "n", "0", "nahi", "नहीं"):
            return False
        raise ValueError("expected yes/no")
    if kind == "date":
        d = clock.parse_date(str(value))
        if d is None:
            raise ValueError("expected a date YYYY-MM-DD")
        if d > clock.today():
            raise ValueError("date cannot be in the future")
        return d.isoformat()
    if kind == "number":
        v = float(str(value).replace(",", "").replace("₹", "").strip())
        if v < 0 or v > 1e9:
            raise ValueError("amount out of range")
        return v
    if kind == "select":
        s = str(value).strip()
        if s not in ENUMS[field]:
            raise ValueError(f"must be one of {sorted(ENUMS[field])}")
        return s
    s = str(value).strip()
    if not s or len(s) > 200:
        raise ValueError("must be 1-200 characters")
    if field == "prior_contact.complaint_number":
        return pii.scrub_reference(s)
    return pii.scrub(s).text


async def apply_answers(case_id: str, answers: dict[str, Any]) -> dict:
    case = repo.get_case(case_id)
    if case["state"] in ("CLOSED", "RESOLVED"):
        raise illegal("This case is closed.")
    errors = []
    coerced: dict[str, Any] = {}
    for field, value in answers.items():
        if field not in ANSWERABLE:
            errors.append({"field": f"answers.{field}", "message": "Unknown field."})
            continue
        try:
            coerced[field] = _coerce_answer(field, value)
        except (ValueError, TypeError) as e:
            errors.append({"field": f"answers.{field}", "message": str(e)})
    if errors:
        raise validation_error(errors)
    cj = case["case_json"]
    for field, value in coerced.items():
        _set(cj, field, value)
    pc = cj.setdefault("prior_contact", {})
    if coerced.get("prior_contact.contacted_company") is False:
        pc.update(date=None, complaint_number=None, got_reply=None, reply_date=None, satisfied_with_reply=None)
    if coerced.get("prior_contact.got_reply") is False:
        pc.update(reply_date=None, satisfied_with_reply=None)
    if "counterparty.name" in coerced and not _get(cj, "counterparty.type"):
        for pat, _name, typ in COUNTERPARTIES:
            if re.search(pat, coerced["counterparty.name"].lower()):
                cj["counterparty"]["type"] = typ
                if cj.get("category") in (None, "other"):
                    cj["category"] = {"bank": "bank_payment", "payment_app": "bank_payment",
                                      "airline": "travel", "telco": "telecom", "insurer": "insurance"}.get(
                        typ, "ecommerce_refund")
                break
    refresh_derived(case)
    repo.add_timeline(case, "answers_saved", ", ".join(coerced))
    repo.save_case(case)
    if repo.get_steps(case_id):
        from . import planning
        await planning.plan_case(case_id, use_llm=False, timeline=False)
        case = repo.get_case(case_id)
    bus.publish(case_id, "case_updated", {"state": case["state"]})
    return case
