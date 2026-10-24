"""Test setup: mock mode, instant agent replays, fixed demo date, a fresh SQLite file per test."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_DIR))

os.environ.update({
    "MOCK_MODE": "1", "MOCK_DELAY_SCALE": "0", "SCHEDULER_ENABLED": "0", "DEMO_BASE_DATE": "2026-10-24",
    "STARTUP_RULE_REFRESH": "1", "RECORD_FIXTURES": "0", "RATE_LIMIT_PER_MIN": "10000",
    "TINYFISH_API_KEY": "", "SANDBOX_PUBLIC_URL": "https://sandbox.example.test",
})


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    from app import db
    from app.config import reset_settings_cache
    from app.llm import gateway as gw
    from app.tinyfish import client as tfc

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("EVAL_DIR", str(tmp_path / "eval"))
    reset_settings_cache()
    db.close_db()
    gw.reset_gateway(None)
    tfc.reset_tinyfish(None)
    from app.services import runs
    runs._portal_locks.clear()
    yield tmp_path
    db.close_db()
    reset_settings_cache()


@pytest.fixture()
def client(fresh_db):
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        wait_for_runs(c)
        yield c


def wait_for_runs(c, run_id: str | None = None, timeout: float = 10.0) -> dict | None:
    """Poll until a run (or every queued/running run) is finished."""
    import time

    from app import db

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run_id:
            r = c.get(f"/api/runs/{run_id}").json()
            if r["status"] not in ("queued", "running"):
                return r
        else:
            row = db.q1("SELECT COUNT(*) n FROM runs WHERE status IN ('queued','running')")
            if row["n"] == 0:
                return None
        time.sleep(0.05)
    raise AssertionError(f"run {run_id or '(all)'} did not finish in {timeout}s")
