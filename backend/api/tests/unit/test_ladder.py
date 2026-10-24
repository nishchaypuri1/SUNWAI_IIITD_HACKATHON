from datetime import date

from app.core.ladder import RuleInfo, plan

RBI = RuleInfo("rule_rbi", "rbi_cms", wait_days=30, window_days=90, counts_from="later_of_wait_end_or_last_reply",
               effective_from=date(2026, 7, 1), freshness="live", verified=True)
CG = RuleInfo("rule_cg", "company_grievance", wait_days=30, freshness="live", verified=True)
RULES = {"rbi_cms": RBI, "company_grievance": CG}
TODAY = date(2026, 10, 24)


def bank_case(**pc):
    base = {"contacted_company": True, "date": None, "complaint_number": None, "got_reply": False,
            "reply_date": None, "satisfied_with_reply": None}
    base.update(pc)
    return {"category": "bank_payment", "counterparty": {"name": "PhonePe", "type": "payment_app"},
            "prior_contact": base, "incident_date": "2026-10-01"}


def test_no_reply_contract_example():
    r = plan(bank_case(date="2026-10-02"), RULES, TODAY)
    s1, s2 = r.steps
    assert (s1.status, s1.due_at) == ("waiting", date(2026, 11, 1))
    assert (s2.status, s2.opens_at, s2.closes_at) == ("locked", date(2026, 11, 1), date(2027, 1, 30))
    assert (s2.opens_at - TODAY).days == 8
    assert (s2.closes_at - TODAY).days == 98
    assert not s2.needs_verification


def test_unsatisfactory_reply_before_wait_end():
    r = plan(bank_case(date="2026-10-02", got_reply=True, reply_date="2026-10-15", satisfied_with_reply=False),
             RULES, TODAY)
    s2 = r.steps[1]
    assert (s2.status, s2.opens_at, s2.closes_at) == ("open", date(2026, 10, 15), date(2027, 1, 30))
    assert r.steps[0].status == "due"


def test_reply_after_wait_end_uses_later_date():
    r = plan(bank_case(date="2026-09-01", got_reply=True, reply_date="2026-10-20", satisfied_with_reply=False),
             RULES, TODAY)
    assert r.steps[1].closes_at == date(2027, 1, 18)
    assert r.steps[1].opens_at == date(2026, 10, 1)


def test_pre_scheme_complaint_flags_2021():
    r = plan(bank_case(date="2026-06-15"), RULES, TODAY)
    assert r.steps[1].needs_verification is True
    assert any("2021" in w for w in r.warnings)


def test_expired_after_close():
    r = plan(bank_case(date="2026-08-01"), RULES, date(2026, 12, 1))
    assert r.steps[1].status == "expired"
    assert r.steps[1].closes_at == date(2026, 11, 29)


def test_not_contacted_opens_step1_and_locks_step2():
    r = plan(bank_case(contacted_company=False), RULES, TODAY)
    assert r.steps[0].status == "open" and r.steps[0].opens_at == TODAY and r.steps[0].due_at is None
    assert r.steps[1].status == "locked" and r.steps[1].opens_when


def test_satisfied_skips_ombudsman():
    r = plan(bank_case(date="2026-10-01", got_reply=True, reply_date="2026-10-10", satisfied_with_reply=True),
             RULES, TODAY)
    assert r.steps[0].status == "done"
    assert r.steps[1].status == "skipped"


def test_unknown_complaint_date():
    r = plan(bank_case(date=None), RULES, TODAY)
    assert r.steps[1].opens_at is None and r.steps[1].opens_when and r.steps[1].needs_verification


def test_seven_day_warning():
    r = plan(bank_case(date="2026-07-02"), RULES, TODAY)
    assert r.steps[1].status == "open" and r.steps[1].closes_at == date(2026, 10, 30)
    assert any("Less than 7 days" in w for w in r.warnings)


def test_boundaries_are_inclusive():
    # wait ends 2026-11-01: on that day the Ombudsman step opens; window last day 2027-01-30 is still open
    assert plan(bank_case(date="2026-10-02"), RULES, date(2026, 11, 1)).steps[1].status == "open"
    assert plan(bank_case(date="2026-10-02"), RULES, date(2027, 1, 30)).steps[1].status == "open"
    assert plan(bank_case(date="2026-10-02"), RULES, date(2027, 1, 31)).steps[1].status == "expired"


def test_seed_rule_warns_and_needs_verification():
    seed = RuleInfo("seed", "rbi_cms", 30, 90, "later_of_wait_end_or_last_reply", date(2026, 7, 1), "seed", False)
    r = plan(bank_case(date="2026-10-02"), {"rbi_cms": seed}, TODAY)
    assert r.steps[1].needs_verification
    assert any("not freshly verified" in w for w in r.warnings)


def test_unclear_window_never_invents_a_deadline():
    unclear = RuleInfo("u", "rbi_cms", 30, 90, "unclear", date(2026, 7, 1), "live", False)
    r = plan(bank_case(date="2026-09-01"), {"rbi_cms": unclear}, TODAY)
    assert r.steps[1].closes_at is None and r.steps[1].needs_verification


def test_consumer_route():
    case = {"category": "ecommerce_refund", "counterparty": {"name": "Amazon", "type": "merchant"},
            "prior_contact": {"contacted_company": True, "date": "2026-10-05", "got_reply": False},
            "incident_date": "2026-10-03"}
    r = plan(case, {}, TODAY)
    assert [s.forum_id for s in r.steps] == ["company_grievance", "nch", "consumer_commission"]
    assert r.steps[1].status == "open" and r.steps[1].needs_verification
    assert r.steps[2].status == "locked" and r.steps[2].closes_at is None


def test_out_of_scope_category():
    case = {"category": "telecom", "counterparty": {"name": "Jio", "type": "telco"},
            "prior_contact": {"contacted_company": False}}
    r = plan(case, {}, TODAY)
    assert [s.forum_id for s in r.steps] == ["company_grievance", "nch"]
    assert any("not covered yet" in w for w in r.warnings)


def test_user_submitted_override_keeps_step_waiting():
    r = plan(bank_case(date="2026-09-01"), RULES, TODAY, {2: {"submitted_at": "2026-10-20", "ack_number": "CMS1"}})
    assert r.steps[1].status == "waiting" and r.steps[1].ack_number == "CMS1"
