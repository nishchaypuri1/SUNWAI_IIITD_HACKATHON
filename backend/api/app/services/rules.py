"""Official rules: storage, freshness, and live refresh (TinyFish Search -> Fetch -> P2 -> verify quotes in code).

A value is "verified" only if its evidence quote is actually found in the fetched official text.
Values that cannot be verified keep their previous number but are flagged (needs_verification) and listed
in `unknowns`.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from .. import clock, db, repo
from ..config import get_settings
from ..core.ladder import RuleInfo
from ..errors import not_found
from ..events import bus
from ..llm.gateway import gateway
from ..tinyfish.client import TinyFishError, tinyfish
from . import runs

log = logging.getLogger("sunwai.rules")

OFFICIAL = re.compile(r"(^|\.)(rbi\.org\.in|gov\.in|nic\.in)$")
QUERIES = {
    "rbi_cms": ["Reserve Bank Integrated Ombudsman Scheme 2026", "RB-IOS 2026 salient features"],
    "company_grievance": ["Reserve Bank Integrated Ombudsman Scheme 2026"],
    "nch": ["National Consumer Helpline how to register complaint consumerhelpline.gov.in"],
    "consumer_commission": ["Consumer Protection Act 2019 limitation period filing complaint two years"],
}
KEY_FIELDS = {
    "rbi_cms": ["wait_days_before_escalation", "filing_window_days", "filing_window_counts_from"],
    "company_grievance": ["wait_days_before_escalation"],
    "nch": ["wait_days_before_escalation"],
    "consumer_commission": ["filing_window_days"],
}
SNIPPET_FIELD = {"rbi_cms": "filing_window_days", "company_grievance": "wait_days_before_escalation",
                 "nch": "wait_days_before_escalation", "consumer_commission": "filing_window_days"}
VALUE_FIELDS = ["scheme_name", "effective_from", "wait_days_before_escalation", "filing_window_days",
                "filing_window_counts_from"]


# ------------------------------------------------------------ reading
def active_row(forum_id: str) -> dict:
    r = db.q1("SELECT * FROM rules WHERE forum_id=? AND active=1 ORDER BY version DESC", (forum_id,))
    if r is None:
        raise not_found("Rule")
    d = dict(r)
    d["data"] = db.loads(d["data"], {})
    return d


def freshness(row: dict) -> str:
    fetched = clock.parse_dt(row.get("fetched_at"))
    if fetched and (clock.real_now() - fetched) < timedelta(hours=get_settings().rule_ttl_hours):
        return "live"
    if row.get("last_refresh_failed"):
        return "stale"
    if fetched:
        return "cached"
    return "seed"


def _shorten(quote: str | None, max_words: int = 25) -> str | None:
    if not quote:
        return None
    words = quote.split()
    if len(words) <= max_words:
        return quote.strip()
    return " ".join(words[:max_words - 4]) + " … " + " ".join(words[-3:])


def rule_ref(forum_id: str) -> dict | None:
    try:
        row = active_row(forum_id)
    except Exception:
        return None
    data = row["data"]
    url = data.get("source_url")
    ev = (data.get("evidence") or {}).get(SNIPPET_FIELD.get(forum_id, ""), None)
    if not ev:
        ev = next((v for v in (data.get("evidence") or {}).values() if v), None)
    return {
        "rule_id": row["id"], "freshness": freshness(row), "source_url": url,
        "source_domain": data.get("source_domain") or (urlparse(url).netloc.removeprefix("www.") if url else None),
        "source_title": data.get("source_title"), "fetched_at": row.get("fetched_at"),
        "evidence_snippet": _shorten(ev),
    }


def get_rule(forum_id: str) -> dict:
    repo.get_forum(forum_id)  # 404 for unknown forums
    row = active_row(forum_id)
    d = row["data"]
    ref = rule_ref(forum_id) or {}
    counts = d.get("filing_window_counts_from") or "unclear"
    return {
        **ref,
        "forum_id": forum_id, "scheme_name": d.get("scheme_name"), "effective_from": d.get("effective_from"),
        "wait_days_before_escalation": d.get("wait_days_before_escalation"),
        "filing_window_days": d.get("filing_window_days"), "filing_window_counts_from": counts,
        "evidence": {k: v for k, v in (d.get("evidence") or {}).items()},
        "eligibility_conditions": d.get("eligibility_conditions") or [], "exclusions": d.get("exclusions") or [],
        "documents_required": d.get("documents_required") or [], "unknowns": d.get("unknowns") or [],
        "confidence": d.get("confidence") or "seed", "changed_from_previous": d.get("changed_from_previous"),
        "superseded_value_note": d.get("superseded_value_note"),
    }


def rule_info(forum_id: str) -> RuleInfo | None:
    try:
        row = active_row(forum_id)
    except Exception:
        return None
    d = row["data"]
    return RuleInfo(
        rule_id=row["id"], forum_id=forum_id, wait_days=d.get("wait_days_before_escalation"),
        window_days=d.get("filing_window_days"), counts_from=d.get("filing_window_counts_from") or "unclear",
        effective_from=clock.parse_date(d.get("effective_from")), freshness=freshness(row),
        verified=bool(d.get("verified")), fetched_at=row.get("fetched_at"),
        limitation_days=d.get("filing_window_days") if forum_id == "consumer_commission" else None,
    )


def all_rule_infos() -> dict[str, RuleInfo]:
    out = {}
    for fid in ("company_grievance", "rbi_cms", "nch", "consumer_commission"):
        ri = rule_info(fid)
        if ri:
            out[fid] = ri
    return out


# ------------------------------------------------------------ verification
def _norm(s: str) -> str:
    s = s.lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"[*_`#>]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_in_text(quote: str | None, text: str) -> bool:
    if not quote or not text:
        return False
    hay = _norm(text)
    pos = 0
    for frag in re.split(r"…|\.\.\.", quote):
        f = _norm(frag).strip(" .,;:")
        if not f:
            continue
        i = hay.find(f, pos)
        if i < 0:
            return False
        pos = i + len(f)
    return True


def _verify(extracted: dict, text: str, prev: dict) -> tuple[dict, list[str], dict]:
    """Return (values, unknowns, evidence) keeping only evidence found verbatim in the text."""
    evidence = dict(extracted.get("evidence") or {})
    values: dict[str, Any] = {}
    unknowns = list(extracted.get("unknowns") or [])
    for f in ("effective_from", "wait_days_before_escalation", "filing_window_days", "filing_window_counts_from"):
        val = extracted.get(f)
        q = evidence.get(f)
        ok = val not in (None, "unclear") and quote_in_text(q, text)
        if ok:
            values[f] = val
        else:
            evidence[f] = None
            if f not in unknowns and (prev.get(f) not in (None, "unclear") or val not in (None, "unclear")):
                unknowns.append(f)
    if extracted.get("scheme_name"):
        values["scheme_name"] = extracted["scheme_name"]
    return values, unknowns, {k: v for k, v in evidence.items() if k in (
        "effective_from", "wait_days_before_escalation", "filing_window_days", "filing_window_counts_from")}


# ------------------------------------------------------------ refresh
def start_refresh(forum_id: str) -> str:
    repo.get_forum(forum_id)
    run = repo.create_run(case_id=None, step_ordinal=None, kind="rule_refresh", portal_mode="live",
                          portal_url="https://api.search.tinyfish.ai", status="running")
    repo.update_run(run["id"], started_at=clock.now_iso())
    runs.start(run["id"], _refresh(run["id"], forum_id))
    return run["id"]


async def refresh_now(forum_id: str) -> str:
    """Synchronous variant used at startup and by tests."""
    run = repo.create_run(case_id=None, step_ordinal=None, kind="rule_refresh", portal_mode="live",
                          portal_url="https://api.search.tinyfish.ai", status="running")
    repo.update_run(run["id"], started_at=clock.now_iso())
    await _refresh(run["id"], forum_id)
    return run["id"]


async def _refresh(run_id: str, forum_id: str) -> None:
    relay = runs.Relay(run_id, None, "tinyfish.ai")
    tf = tinyfish()
    try:
        prev_row = active_row(forum_id)
        prev = prev_row["data"]
        await relay.note(f"Searching official sources for the {forum_id} rule…")
        results: list[dict] = []
        for qtext in QUERIES.get(forum_id, []):
            results += await tf.search(qtext)
        seen, ranked = set(), []
        for r in sorted(results, key=lambda r: 0 if OFFICIAL.search(urlparse(r["url"]).netloc) else 1):
            if r["url"] not in seen:
                seen.add(r["url"])
                ranked.append(r)
        if not ranked:
            raise TinyFishError("TASK_FAILED", "No search results for the official rule")
        await relay.note(f"Found {len(ranked)} candidate page(s); fetching the top 2 live")
        fetched = await tf.fetch([r["url"] for r in ranked[:2]], ttl=0)
        docs = [d for d in fetched["results"] if (d.get("text") or "").strip()]
        if not docs:
            raise TinyFishError("TASK_FAILED", "Could not fetch any official page text")
        best: tuple[int, dict, dict, list, dict] | None = None
        for doc in docs[:2]:
            text = doc["text"][:120_000]
            host = urlparse(doc.get("final_url") or doc["url"]).netloc
            await relay.note(f"Fetched {host} ({len(text):,} chars); extracting the rule")
            extracted = await gateway().run("P2", {"forum_id": forum_id, "source_url": doc["url"],
                                                   "official_text": text})
            values, unknowns, evidence = _verify(extracted, text, prev)
            score = sum(1 for f in KEY_FIELDS.get(forum_id, []) if f in values)
            if best is None or score > best[0]:
                best = (score, doc, values, unknowns, {**extracted, "evidence": evidence})
        assert best is not None
        score, doc, values, unknowns, extracted = best
        url = doc.get("final_url") or doc["url"]
        host = urlparse(url).netloc.removeprefix("www.")
        official = bool(OFFICIAL.search(host))
        verified = score == len(KEY_FIELDS.get(forum_id, [])) and score > 0
        await relay.note(f"Verified {score} of {len(KEY_FIELDS.get(forum_id, []))} key value(s) against the "
                         f"{'official' if official else 'secondary'} text")
        new = dict(prev)
        changes = []
        for f in VALUE_FIELDS:
            if f in values and values[f] != prev.get(f):
                changes.append({"field": f, "old": prev.get(f), "new": values[f]})
                new[f] = values[f]
        new["evidence"] = extracted["evidence"]
        new["unknowns"] = unknowns
        new["verified"] = verified
        new["source_url"] = url
        new["source_domain"] = host
        new["source_title"] = doc.get("title") or None
        new["confidence"] = ("high" if official else "medium") if verified else "low"
        for k in ("eligibility_conditions", "exclusions", "documents_required"):
            if extracted.get(k):
                new[k] = extracted[k][:8]
        if extracted.get("superseded_value_note"):
            new["superseded_value_note"] = extracted["superseded_value_note"]
        new["changed_from_previous"] = changes or None
        fetched_at = doc.get("recorded_at") or clock.real_now_iso()
        version = int(db.q1("SELECT MAX(version) v FROM rules WHERE forum_id=?", (forum_id,))["v"] or 0) + 1
        new_id = f"rule_{forum_id}_v{version}"
        with db.tx() as c:
            c.execute("UPDATE rules SET active=0 WHERE forum_id=?", (forum_id,))
            c.execute("INSERT INTO rules(id, forum_id, version, active, data, fetched_at, created_at, "
                      "last_refresh_failed) VALUES(?,?,?,?,?,?,?,0)",
                      (new_id, forum_id, version, 1, db.dumps(new), fetched_at, clock.real_now_iso()))
        if changes:
            bus.publish(None, "rule_changed", {"forum_id": forum_id, "changes": changes, "source_url": url})
        runs.finish(run_id, "completed", result_json={"rule_id": new_id, "changes": changes, "verified": verified})
        bus.publish(None, "run_completed", {"run_id": run_id, "kind": "rule_refresh"})
        from . import planning
        planning.recompute_all(rule_changed_forum=forum_id if changes else None)
    except TinyFishError as e:
        _mark_failed(forum_id)
        payload = runs.tinyfish_error_payload(e.code, e.message)
        runs.finish(run_id, "failed", error=payload)
        bus.publish(None, "run_failed", {"run_id": run_id, "error_code": payload["code"],
                                         "message": payload["message"], "retryable": payload["retryable"]})
    except Exception as e:  # LLM_UNAVAILABLE or unexpected
        log.exception("Rule refresh failed for %s", forum_id)
        _mark_failed(forum_id)
        code = getattr(e, "code", "INTERNAL")
        runs.finish(run_id, "failed", error={"code": code, "message": "Rule refresh failed.", "retryable": True})
        bus.publish(None, "run_failed", {"run_id": run_id, "error_code": code, "message": "Rule refresh failed.",
                                         "retryable": True})


def _mark_failed(forum_id: str) -> None:
    db.ex("UPDATE rules SET last_refresh_failed=1 WHERE forum_id=? AND active=1", (forum_id,))


def needs_refresh(forum_id: str) -> bool:
    try:
        return freshness(active_row(forum_id)) != "live"
    except Exception:
        return False

