"""The 15 scenario files: routing and deadlines must match hand-computed expectations exactly."""
import json
from datetime import date
from pathlib import Path

import pytest

SCEN = sorted((Path(__file__).resolve().parent.parent / "scenarios").glob("*.json"))


@pytest.mark.parametrize("path", SCEN, ids=[p.stem for p in SCEN])
def test_scenario(client, path):
    sc = json.loads(path.read_text())
    days = (date.fromisoformat(sc["today"]) - date(2026, 10, 24)).days
    if days:
        client.post("/api/demo/clock", json={"advance_days": days})
    case = client.post("/api/cases", data={"text": sc["text"]}).json()
    for field in sc["expected"]["missing_contains"]:
        assert field in case["missing_fields"], (field, case["missing_fields"])
    case = client.post(f"/api/cases/{case['id']}/plan").json()
    exp = sc["expected"]
    assert [s["forum"]["id"] for s in case["steps"]] == exp["route"]
    for want in exp["steps"]:
        got = case["steps"][want["ordinal"] - 1]
        for k, v in want.items():
            assert got[k] == v, (sc["id"], want["ordinal"], k, got[k], v)
    for w in exp["warnings_contain"]:
        assert any(w in x for x in case["warnings"]), (w, case["warnings"])


def test_there_are_fifteen():
    assert len(SCEN) == 15
