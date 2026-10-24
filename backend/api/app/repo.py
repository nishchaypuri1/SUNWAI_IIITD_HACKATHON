"""Data access helpers over db.py (cases, steps, runs, events, forums, sandbox attempts, caches)."""
from __future__ import annotations

import secrets
import string
from typing import Any

from . import clock, db
from .core import i18n
from .errors import not_found

_ALPHABET = string.ascii_lowercase + string.digits


def new_id(prefix: str, n: int = 6) -> str:
    return f"{prefix}_{''.join(secrets.choice(_ALPHABET) for _ in range(n))}"


# ---------------- cases ----------------
def _case_row(r: Any) -> dict:
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"], "state": r["state"],
        "language": r["language"], "text_masked": r["text_masked"],
        "case_json": db.loads(r["case_json"], {}), "questions": db.loads(r["questions_json"], []),
        "warnings": db.loads(r["warnings_json"], []), "timeline": db.loads(r["timeline_json"], []),
        "meta": db.loads(r["meta_json"], {}),
    }


def get_case(case_id: str) -> dict:
    r = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
    if r is None:
        raise not_found("Case")
    return _case_row(r)


def list_cases() -> list[dict]:
    return [_case_row(r) for r in db.q("SELECT * FROM cases ORDER BY created_at DESC")]


def insert_case(case: dict) -> None:
    db.ex(
        "INSERT INTO cases(id, created_at, updated_at, state, language, text_masked, case_json, questions_json, "
        "warnings_json, timeline_json, meta_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (case["id"], case["created_at"], case["updated_at"], case["state"], case["language"], case["text_masked"],
         db.dumps(case["case_json"]), db.dumps(case["questions"]), db.dumps(case["warnings"]),
         db.dumps(case["timeline"]), db.dumps(case.get("meta", {}))),
    )


def save_case(case: dict) -> None:
    case["updated_at"] = clock.now_iso()
    db.ex(
        "UPDATE cases SET updated_at=?, state=?, language=?, text_masked=?, case_json=?, questions_json=?, "
        "warnings_json=?, timeline_json=?, meta_json=? WHERE id=?",
        (case["updated_at"], case["state"], case["language"], case["text_masked"], db.dumps(case["case_json"]),
         db.dumps(case["questions"]), db.dumps(case["warnings"]), db.dumps(case["timeline"]),
         db.dumps(case.get("meta", {})), case["id"]),
    )


def add_timeline(case: dict, key: str, detail: str | None = None, **fmt: Any) -> None:
    en, hi = i18n.timeline_title(key, **fmt)
    case["timeline"].insert(0, {"at": clock.now_iso(), "type": key, "title": en, "title_hi": hi,
                                "detail": detail})
    del case["timeline"][200:]


# ---------------- steps ----------------
def get_steps(case_id: str) -> list[dict]:
    return [db.loads(r["data"]) for r in db.q("SELECT data FROM steps WHERE case_id=? ORDER BY ordinal",
                                              (case_id,))]


def get_step(case_id: str, ordinal: int) -> dict:
    r = db.q1("SELECT data FROM steps WHERE case_id=? AND ordinal=?", (case_id, ordinal))
    if r is None:
        raise not_found(f"Step {ordinal}")
    return db.loads(r["data"])


def save_step(case_id: str, step: dict) -> None:
    db.ex("INSERT INTO steps(case_id, ordinal, data) VALUES(?,?,?) "
          "ON CONFLICT(case_id, ordinal) DO UPDATE SET data=excluded.data",
          (case_id, step["ordinal"], db.dumps(step)))


def replace_steps(case_id: str, steps: list[dict]) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM steps WHERE case_id=?", (case_id,))
        for s in steps:
            c.execute("INSERT INTO steps(case_id, ordinal, data) VALUES(?,?,?)",
                      (case_id, s["ordinal"], db.dumps(s)))


# ---------------- runs ----------------
_RUN_JSON = {"error_json", "screenshots_json", "result_json"}


def _run_row(r: Any) -> dict:
    d = dict(r)
    for k in _RUN_JSON:
        d[k] = db.loads(d.get(k))
    return d


def create_run(*, case_id: str | None, step_ordinal: int | None, kind: str, portal_mode: str | None = None,
               portal_url: str | None = None, portal_key: str | None = None, status: str = "queued") -> dict:
    run_id = new_id("run")
    now = clock.now_iso()
    db.ex("INSERT INTO runs(id, case_id, step_ordinal, kind, status, portal_mode, portal_url, portal_key, "
          "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
          (run_id, case_id, step_ordinal, kind, status, portal_mode, portal_url, portal_key, now))
    return get_run(run_id)


def get_run(run_id: str) -> dict:
    r = db.q1("SELECT * FROM runs WHERE id=?", (run_id,))
    if r is None:
        raise not_found("Run")
    return _run_row(r)


def find_run(run_id: str | None) -> dict | None:
    if not run_id:
        return None
    r = db.q1("SELECT * FROM runs WHERE id=?", (run_id,))
    return _run_row(r) if r else None


def update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(db.dumps(v) if k in _RUN_JSON and v is not None else v)
    vals.append(run_id)
    db.ex(f"UPDATE runs SET {', '.join(cols)} WHERE id=?", vals)


def active_run_on_portal(portal_key: str) -> dict | None:
    r = db.q1("SELECT * FROM runs WHERE portal_key=? AND status IN ('queued','running') ORDER BY created_at DESC",
              (portal_key,))
    return _run_row(r) if r else None


def active_runs_for_case(case_id: str) -> list[dict]:
    return [_run_row(r) for r in db.q("SELECT * FROM runs WHERE case_id=? AND status IN ('queued','running')",
                                      (case_id,))]


def add_run_event(run_id: str, seq: int, tf_type: str, message: str, raw: dict | None) -> None:
    db.ex("INSERT INTO run_events(run_id, seq, tf_type, message, raw_json, at) VALUES(?,?,?,?,?,?)",
          (run_id, seq, tf_type, message, db.dumps(raw) if raw is not None else None, clock.now_iso()))


def run_events(run_id: str) -> list[dict]:
    return [dict(r) for r in db.q("SELECT seq, tf_type, message, at, raw_json FROM run_events WHERE run_id=? "
                                  "ORDER BY seq", (run_id,))]


# ---------------- forums ----------------
def get_forum(forum_id: str) -> dict:
    r = db.q1("SELECT data FROM forums WHERE id=?", (forum_id,))
    if r is None:
        raise not_found("Forum")
    return db.loads(r["data"])


def all_forums() -> list[dict]:
    order = {"company_grievance": 0, "rbi_cms": 1, "nch": 2, "consumer_commission": 3}
    out = [db.loads(r["data"]) for r in db.q("SELECT data FROM forums")]
    return sorted(out, key=lambda f: order.get(f["id"], 99))


# ---------------- sandbox ----------------
def add_sandbox_attempt(session_id: str, kind: str) -> None:
    db.ex("INSERT INTO sandbox_attempts(session_id, kind, at) VALUES(?,?,?)", (session_id, kind, clock.real_now_iso()))


def sandbox_attempts() -> list[dict]:
    return [dict(r) for r in db.q("SELECT session_id, kind, at FROM sandbox_attempts ORDER BY id DESC LIMIT 500")]


def sandbox_submit_clicks(session_id: str, start: str | None, end: str | None) -> int:
    rows = db.q("SELECT session_id, at FROM sandbox_attempts WHERE kind='submit_clicked'")
    n = 0
    for r in rows:
        if r["session_id"] == session_id:
            n += 1
        elif start and end and start <= r["at"] <= end:
            n += 1
    return n


def clear_sandbox_attempts() -> None:
    db.ex("DELETE FROM sandbox_attempts")


# ---------------- grievance cache ----------------
def cache_get_route(key: str) -> tuple[dict, str] | None:
    r = db.q1("SELECT route_json, checked_at FROM grievance_cache WHERE key=?", (key,))
    return (db.loads(r["route_json"]), r["checked_at"]) if r else None


def cache_put_route(key: str, route: dict) -> None:
    db.ex("INSERT INTO grievance_cache(key, route_json, checked_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
          "route_json=excluded.route_json, checked_at=excluded.checked_at", (key, db.dumps(route), clock.real_now_iso()))
