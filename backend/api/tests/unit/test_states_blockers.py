import pytest

from app.core import states
from app.errors import ApiError
from app.tinyfish import blockers


def test_only_human_can_submit():
    with pytest.raises(ApiError) as e:
        states.transition({"ordinal": 1, "status": "review_ready"}, "submitted")
    assert e.value.status == 409
    s = {"ordinal": 1, "status": "review_ready"}
    states.transition(s, "submitted", actor="human")
    assert s["status"] == "submitted"


@pytest.mark.parametrize("cur,new", [("locked", "filling"), ("open", "submitted"), ("waiting", "filling"),
                                     ("done", "open"), ("filling", "waiting"), ("submitted", "due")])
def test_illegal_transitions(cur, new):
    with pytest.raises(ApiError) as e:
        states.transition({"ordinal": 1, "status": cur}, new, actor="human")
    assert e.value.code == "ILLEGAL_TRANSITION"


@pytest.mark.parametrize("status,ok", [("open", True), ("blocked", True), ("locked", False), ("waiting", False),
                                       ("review_ready", False)])
def test_prefill_guard(status, ok):
    step = {"ordinal": 1, "status": status, "forum_id": "company_grievance"}
    if ok:
        states.assert_can_prefill(step)
    else:
        with pytest.raises(ApiError):
            states.assert_can_prefill(step)


def test_commission_never_automated():
    with pytest.raises(ApiError):
        states.assert_can_prefill({"ordinal": 3, "status": "open", "forum_id": "consumer_commission"})


def test_prepare_next_guard():
    states.assert_can_prepare_next({"ordinal": 1, "status": "due"})
    states.assert_can_prepare_next({"ordinal": 1, "status": "waiting",
                                    "status_checks": [{"normalized_status": "replied"}]})
    with pytest.raises(ApiError):
        states.assert_can_prepare_next({"ordinal": 1, "status": "waiting", "status_checks": []})


def test_derive_case_state():
    steps = [{"ordinal": 1, "status": "due"}, {"ordinal": 2, "status": "open"}]
    assert states.derive_case_state("WAITING", steps) == "DUE"
    steps[1]["escalation_prepared"] = True
    assert states.derive_case_state("DUE", steps) == "ESCALATION_READY"
    assert states.derive_case_state("CLOSED", steps) == "CLOSED"


def test_blockers():
    assert blockers.detect({"blocker": "otp"}, {}, []) == "otp"
    assert blockers.detect({}, {"profile_hint": {"reason": "auth_wall"}}, []) == "login"
    assert blockers.detect({}, {"profile_hint": {"reason": "bot_challenge"}}, []) == "bot_challenge"
    assert blockers.detect({}, {"error": {"code": "SITE_BLOCKED"}}, []) == "bot_challenge"
    assert blockers.detect({"reached_review_screen": False}, {}, ["Please solve the CAPTCHA"]) == "captcha"
    assert blockers.detect({"reached_review_screen": True, "blocker": "none"}, {}, ["login link in footer"]) is None
