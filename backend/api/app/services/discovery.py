"""Grievance discovery (E11): TinyFish Search for the company's own grievance page, then a read-only G3 agent
run that reads the form URL / email / escalation levels. Results are validated and cached for 7 days."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import timedelta
from urllib.parse import urlparse

from .. import clock, repo
from ..config import get_settings
from ..core import states
from ..errors import illegal
from ..events import bus
from ..tinyfish import goals
from ..tinyfish.client import FIXTURES, TinyFishError, tinyfish
from . import runs

log = logging.getLogger("sunwai.discovery")

AGGREGATORS = re.compile(r"(complaint|consumer|review|forum|quora|reddit|mouthshut|justdial|voxya|akosha|"
                         r"facebook|twitter|x\.com|youtube|linkedin|wikipedia|medium|blog)", re.I)
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _key(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", company.lower())


def _pick(results: list[dict], company: str) -> str | None:
    token = _key(company)[:8]
    own = [r for r in results if token and token in urlparse(r["url"]).netloc.replace("-", "").replace(".", "")]
    pool = own or [r for r in results if not AGGREGATORS.search(urlparse(r["url"]).netloc)]
    for r in pool:
        if re.search(r"grievance|complaint|nodal|redress", r["url"] + " " + r.get("title", ""), re.I):
            return r["url"]
    return pool[0]["url"] if pool else None


def _mock_route(company: str) -> dict | None:
    for path in (FIXTURES / "discover").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("match") and data["match"] in company.lower():
            return data["result"]
    return None


def _clean(raw: dict, page_url: str, found_via: str, page_text: str = "") -> dict:
    def s(v: object) -> str | None:
        v = str(v or "").strip()
        return v or None

    quote = s(raw.get("evidence_quote"))
    if quote and len(quote.split()) > 20:
        quote = " ".join(quote.split()[:20])
    email = s(raw.get("grievance_email"))
    if email:
        seen = email.lower() in (quote or "").lower() or email.lower() in page_text.lower()
        if not EMAIL.match(email) or not seen:
            email = None
    form = s(raw.get("grievance_form_url"))
    if form and not form.startswith("http"):
        form = None
    matrix = []
    for m in raw.get("escalation_matrix") or []:
        if isinstance(m, dict) and s(m.get("level")) and s(m.get("contact")):
            matrix.append({"level": s(m["level"])[:120], "contact": s(m["contact"])[:200]})
    return {"grievance_form_url": form, "grievance_email": email, "nodal_officer_name": s(raw.get("nodal_officer_name")),
            "escalation_matrix": matrix[:6], "page_url": page_url, "evidence_quote": quote, "found_via": found_via,
            "checked_at": clock.now_iso()}


async def start(case_id: str, ordinal: int) -> str:
    case = repo.get_case(case_id)
    step = repo.get_step(case_id, ordinal)
    states.assert_can_discover(step)
    company = (case["case_json"].get("counterparty") or {}).get("name")
    if not company:
        raise illegal("Tell us which company this is about first (answer the counterparty question).")
    run = repo.create_run(case_id=case_id, step_ordinal=ordinal, kind="discover", portal_mode="live",
                          portal_url="https://api.search.tinyfish.ai")
    repo.update_run(run["id"], status="running", started_at=clock.now_iso())
    bus.publish(case_id, "run_started", {"run_id": run["id"], "kind": "discover", "step_ordinal": ordinal,
                                         "portal_url": "https://api.search.tinyfish.ai", "portal_mode": "live"})
    runs.start(run["id"], _run(run["id"], case_id, ordinal, company))
    return run["id"]


async def _run(run_id: str, case_id: str, ordinal: int, company: str) -> None:
    relay = runs.Relay(run_id, case_id, "tinyfish.ai")
    tf = tinyfish()
    try:
        cached = repo.cache_get_route(_key(company))
        if cached and (clock.real_now() - clock.parse_dt(cached[1])) < timedelta(days=7):
            route = cached[0]
            await relay.note(f"Using the grievance route found for {company} on {cached[1][:10]}")
        else:
            await relay.note(f"Searching for {company}'s grievance redressal page")
            results = await tf.search(f"{company} grievance redressal nodal officer")
            results += await tf.search(f"{company} customer complaint form")
            url = _pick(results, company)
            if not url:
                raise TinyFishError("TASK_FAILED", "Could not find the company's grievance page")
            await relay.note(f"Reading {urlparse(url).netloc} with the web agent (read-only)")
            mock_raw = _mock_route(company) if get_settings().mock_mode else None
            complete = await tf.run_sse(url, goals.g3_discover(company), on_event=relay,
                                        output_schema=goals.DISCOVER_SCHEMA, agent_config=goals.DISCOVER_AGENT_CONFIG,
                                        mock_fixture="discover", mock_result=mock_raw)
            raw = complete.get("result") if isinstance(complete.get("result"), dict) else {}
            page_text = ""
            if raw.get("grievance_email") and not get_settings().mock_mode:
                try:  # verify the email really is on the page (TinyFish Fetch, live)
                    fetched = await tf.fetch([url], ttl=0)
                    page_text = " ".join(r.get("text", "") for r in fetched["results"])
                except TinyFishError:
                    page_text = ""
            route = _clean(raw, url, "mock" if get_settings().mock_mode else "tinyfish_search+agent", page_text)
            if route["grievance_form_url"] or route["grievance_email"] or route["escalation_matrix"]:
                repo.cache_put_route(_key(company), route)
        case = repo.get_case(case_id)
        step = repo.get_step(case_id, ordinal)
        step["grievance_route"] = route
        repo.save_step(case_id, step)
        repo.add_timeline(case, "route_found", route.get("grievance_form_url") or route.get("page_url"))
        repo.save_case(case)
        runs.finish(run_id, "completed", result_json=route)
        bus.publish(case_id, "grievance_route_found", {"step_ordinal": ordinal, "grievance_route": route})
        bus.publish(case_id, "run_completed", {"run_id": run_id, "kind": "discover"})
    except TinyFishError as e:
        payload = runs.tinyfish_error_payload(e.code, e.message)
        runs.finish(run_id, "failed", error=payload)
        bus.publish(case_id, "run_failed", {"run_id": run_id, "error_code": payload["code"],
                                            "message": payload["message"], "retryable": payload["retryable"]})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("Discovery run %s crashed", run_id)
        runs.finish(run_id, "failed", error={"code": "INTERNAL", "message": "Discovery failed.", "retryable": True})
        bus.publish(case_id, "run_failed", {"run_id": run_id, "error_code": getattr(e, "code", "INTERNAL"),
                                            "message": "Discovery failed.", "retryable": True})
