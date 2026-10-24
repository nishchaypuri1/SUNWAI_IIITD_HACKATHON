"""Seed static data on startup: forums (always refreshed from file) and rules (only if a forum has none)."""
from __future__ import annotations

import json

from . import clock, db
from .config import DATA_DIR


def _load(name: str) -> list[dict]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def seed_all() -> None:
    for f in _load("forums.seed.json"):
        db.ex("INSERT INTO forums(id, data) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
              (f["id"], db.dumps(f)))
    for r in _load("rules.seed.json"):
        exists = db.q1("SELECT 1 FROM rules WHERE forum_id=?", (r["forum_id"],))
        if exists:
            continue
        data = dict(r)
        data.pop("id")
        data["verified"] = False
        db.ex("INSERT INTO rules(id, forum_id, version, active, data, fetched_at, created_at, last_refresh_failed) "
              "VALUES(?,?,?,?,?,?,?,0)",
              (r["id"], r["forum_id"], 1, 1, db.dumps(data), None, clock.real_now_iso()))


def scenarios() -> list[dict]:
    return _load("scenarios.demo.json")


def sandbox_fields() -> dict:
    """Shared with the frontend sandbox page. Prefer the repo-level contracts copy if present."""
    from .config import REPO_DIR

    shared = REPO_DIR / "contracts" / "sandbox_fields.json"
    path = shared if shared.is_file() else DATA_DIR / "sandbox_fields.json"
    return json.loads(path.read_text(encoding="utf-8"))
