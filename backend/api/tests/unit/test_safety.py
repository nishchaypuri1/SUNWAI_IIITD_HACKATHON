from app.core import safety


def test_clean_run_passes():
    msgs = ["Opening the form", "Typing the amount", "Clicking 'Review' to open the review screen",
            "Review screen reached. Stopping before submit as instructed"]
    assert safety.post_check({"final_submit_clicked": False}, msgs).ok


def test_click_submit_after_review_flags():
    msgs = ["Clicking 'Review'", "Review screen shown", "Clicking the Submit button"]
    v = safety.post_check({}, msgs)
    assert not v.ok and "Submit" in v.evidence


def test_click_confirm_after_review_flags():
    assert not safety.post_check({}, ["Preview loaded", "Pressing Confirm"]).ok


def test_page_text_mentioning_submit_is_not_an_action():
    # The portal's own text ("click Submit to lodge") lands in the result notes, not in the agent's actions.
    result = {"final_submit_clicked": False, "notes": "The page says: please click Submit to lodge your complaint"}
    msgs = ["Clicking 'Review'", "Review screen reached. Stopping before submit as instructed"]
    assert safety.post_check(result, msgs).ok


def test_negations():
    for m in ["Do not click submit", "Stopping before submit", "Without clicking Submit, the review is ready",
              "I will not press confirm"]:
        assert safety.detect_submit_actions(["Review screen", m]) == []


def test_proceed_before_review_is_allowed():
    assert safety.post_check({}, ["Clicking Proceed to the next page", "Typing details"]).ok


def test_submit_before_review_flags():
    assert not safety.post_check({}, ["Clicking Submit"]).ok


def test_agent_flag_and_sandbox_clicks():
    assert not safety.post_check({"final_submit_clicked": True}, []).ok
    assert not safety.post_check({}, [], sandbox_submit_clicks=1).ok


def test_draft_checks():
    issues = safety.check_draft_text("I will sue you. You are legally entitled to a refund, guaranteed.")
    kinds = {i["type"] for i in issues}
    assert {"threat", "legal_advice"} <= kinds
    assert safety.check_draft_text("Please refund Rs 500. Reference 629384710562", allow=["629384710562"]) == []
