"""Pydantic models that mirror contracts/API_CONTRACT.md v1.0 exactly (snake_case, same nullability)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["en", "hi", "hinglish"]
Category = Literal["bank_payment", "ecommerce_refund", "travel", "telecom", "insurance", "other"]
CounterpartyType = Literal["bank", "payment_app", "merchant", "airline", "telco", "insurer", "other"]
DesiredOutcome = Literal["refund", "reversal", "replacement", "apology", "other"]
CaseState = Literal[
    "NEW", "INTAKE_DONE", "LADDER_READY", "AWAITING_APPROVAL", "FILLING", "REVIEW_READY",
    "SUBMITTED_BY_USER", "WAITING", "DUE", "ESCALATION_READY", "RESOLVED", "CLOSED", "BLOCKED", "FAILED",
]
StepStatus = Literal[
    "locked", "open", "filling", "review_ready", "blocked", "submitted", "waiting", "due", "done", "skipped",
    "expired",
]
Blocker = Literal["login", "otp", "captcha", "portal_down", "form_not_found", "bot_challenge"]
RunKind = Literal["fill", "status", "discover", "rule_refresh"]
RunStatus = Literal["queued", "running", "completed", "failed", "blocked", "safety_flagged", "cancelled"]
NormalizedStatus = Literal["received", "in_progress", "replied", "closed", "rejected", "unknown"]
RuleFreshness = Literal["live", "cached", "stale", "seed"]
PortalMode = Literal["sandbox", "live"]
CountsFrom = Literal["later_of_wait_end_or_last_reply", "company_reply", "end_of_wait", "incident", "unclear"]

DISCLAIMER = (
    "Sunwai helps you follow the complaint procedure. It is not legal advice and does not guarantee any "
    "outcome. Please check the official portal before submitting."
)
DISCLAIMER_HI = (
    "सुनवाई आपको शिकायत की प्रक्रिया समझने और उसका पालन करने में मदद करता है। यह कानूनी सलाह नहीं है और किसी "
    "नतीजे की गारंटी नहीं देता। जमा करने से पहले आधिकारिक पोर्टल पर जानकारी ज़रूर जाँचें।"
)


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------- core objects ----------------
class Counterparty(Model):
    name: str | None = None
    type: CounterpartyType | None = None


class PriorContact(Model):
    contacted_company: bool | None = None
    date: str | None = None
    complaint_number: str | None = None
    got_reply: bool | None = None
    reply_date: str | None = None
    satisfied_with_reply: bool | None = None


class CaseJson(Model):
    language: Language = "en"
    category: Category = "other"
    summary: str = ""
    amount_inr: float | None = None
    incident_date: str | None = None
    counterparty: Counterparty = Field(default_factory=Counterparty)
    reference_numbers: list[str] = Field(default_factory=list)
    prior_contact: PriorContact = Field(default_factory=PriorContact)
    desired_outcome: DesiredOutcome | None = None
    evidence_found: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    pii_flags: list[str] = Field(default_factory=list)


class QuestionOption(Model):
    value: str
    label: str
    label_hi: str


class Question(Model):
    field: str
    question: str
    question_hi: str
    input: Literal["date", "number", "text", "select", "boolean"]
    options: list[QuestionOption] | None = None


class Forum(Model):
    id: str
    name: str
    name_hi: str
    kind: Literal["company", "regulator", "helpline", "commission"]
    official_url: str | None = None
    filing_url: str | None = None
    track_url: str | None = None
    sector: Literal["banking", "consumer", "any"]


class RuleRef(Model):
    rule_id: str
    freshness: RuleFreshness
    source_url: str | None = None
    source_domain: str | None = None
    source_title: str | None = None
    fetched_at: str | None = None
    evidence_snippet: str | None = None


class RuleChange(Model):
    field: str
    old: str | float | int | None = None
    new: str | float | int | None = None


class Rule(RuleRef):
    forum_id: str
    scheme_name: str | None = None
    effective_from: str | None = None
    wait_days_before_escalation: int | None = None
    filing_window_days: int | None = None
    filing_window_counts_from: CountsFrom = "unclear"
    evidence: dict[str, str | None] = Field(default_factory=dict)
    eligibility_conditions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    documents_required: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "seed"] = "seed"
    changed_from_previous: list[RuleChange] | None = None
    superseded_value_note: str | None = None


class SafetyIssue(Model):
    type: Literal["legal_advice", "threat", "invented_fact", "pii", "security_bypass"]
    quote: str
    fix: str


class DraftSafety(Model):
    ok: bool
    issues: list[SafetyIssue] = Field(default_factory=list)


class Draft(Model):
    subject: str
    body: str
    placeholders_to_fill: list[str] = Field(default_factory=list)
    attachments_to_mention: list[str] = Field(default_factory=list)
    language: Language = "en"
    word_count: int = 0
    safety: DraftSafety
    edited_by_user: bool = False
    updated_at: str


class EscalationLevel(Model):
    level: str
    contact: str


class GrievanceRoute(Model):
    grievance_form_url: str | None = None
    grievance_email: str | None = None
    nodal_officer_name: str | None = None
    escalation_matrix: list[EscalationLevel] = Field(default_factory=list)
    page_url: str | None = None
    evidence_quote: str | None = None
    found_via: Literal["tinyfish_search+agent", "seed", "mock"]
    checked_at: str


class ReviewField(Model):
    label: str
    value: str | None = None
    filled: bool
    source: str | None = None


class ReviewPacket(Model):
    reached_review_screen: bool
    stopped_before_submit: bool
    safety_flagged: bool
    portal_mode: PortalMode
    portal_url: str
    page_url: str | None = None
    fields: list[ReviewField] = Field(default_factory=list)
    fields_missing: list[str] = Field(default_factory=list)
    blocker: Blocker | None = None
    blocker_message: str | None = None
    notes: str | None = None
    screenshots: list[str] = Field(default_factory=list)
    video_url: str | None = None
    generated_at: str


class RunError(Model):
    code: str
    message: str
    retryable: bool


class Run(Model):
    id: str
    kind: RunKind
    status: RunStatus
    step_ordinal: int | None = None
    tinyfish_run_id: str | None = None
    streaming_url: str | None = None
    video_url: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    events_count: int = 0
    error: RunError | None = None


class RunEventOut(Model):
    seq: int
    tf_type: str
    message: str
    at: str


class RunDetail(Run):
    events: list[RunEventOut] = Field(default_factory=list)


class StatusCheck(Model):
    checked_at: str
    found: bool
    status_text: str | None = None
    normalized_status: NormalizedStatus = "unknown"
    last_updated: str | None = None
    remarks: str | None = None
    blocker: Blocker | None = None


class Step(Model):
    ordinal: int
    forum: Forum
    action: str
    action_hi: str
    why: str
    why_hi: str
    status: StepStatus
    opens_at: str | None = None
    closes_at: str | None = None
    opens_when: str | None = None
    due_at: str | None = None
    days_until_open: int | None = None
    days_until_close: int | None = None
    needs_verification: bool = False
    rule: RuleRef | None = None
    grievance_route: GrievanceRoute | None = None
    draft: Draft | None = None
    latest_run: Run | None = None
    review_packet: ReviewPacket | None = None
    ack_number: str | None = None
    submitted_at: str | None = None
    status_checks: list[StatusCheck] = Field(default_factory=list)


class TimelineItem(Model):
    at: str
    type: str
    title: str
    title_hi: str
    detail: str | None = None


class Case(Model):
    id: str
    created_at: str
    updated_at: str
    state: CaseState
    language: Language
    case_json: CaseJson
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class CaseSummary(Model):
    id: str
    created_at: str
    state: CaseState
    summary: str
    counterparty_name: str | None = None
    amount_inr: float | None = None
    next_deadline: str | None = None
    current_step: int | None = None


class EscalationPack(Model):
    recommendation: Literal["close", "escalate", "wait_more", "needs_user_input"]
    next_forum_id: str | None = None
    filing_deadline: str | None = None
    reasoning: str
    evidence_pack_checklist: list[str] = Field(default_factory=list)
    needs_verification: bool = False
    draft: Draft | None = None


class FieldMapItem(Model):
    label: str
    value: str | None = None
    source: str | None = None


class PrefillPreview(Model):
    portal_mode: PortalMode
    portal_url: str
    field_map: list[FieldMapItem] = Field(default_factory=list)
    draft_excerpt: str = ""
    warnings: list[str] = Field(default_factory=list)


class DemoClock(Model):
    now: str
    today: str
    offset_days: int
    simulated: bool


class ModelRole(Model):
    primary: str
    available: bool


class Health(Model):
    ok: bool
    mock_mode: bool
    version: str
    tinyfish: Literal["ok", "missing_key", "error"]
    models: dict[Literal["intake", "reason", "fast"], ModelRole]


# ---------------- list / wrapper responses ----------------
class Scenario(Model):
    id: str
    title: str
    title_hi: str
    language: Language
    text: str
    image_url: str | None = None


class ScenarioList(Model):
    items: list[Scenario]


class ForumList(Model):
    items: list[Forum]


class CaseList(Model):
    items: list[CaseSummary]


class RunIdResponse(Model):
    run_id: str


class OkResponse(Model):
    ok: bool = True


class SandboxAttemptItem(Model):
    session_id: str
    kind: str
    at: str


class SandboxAttemptsSummary(Model):
    review_reached: int
    submit_clicked: int
    items: list[SandboxAttemptItem]


class SandboxStatus(Model):
    complaint_number: str
    status_text: str
    last_updated: str
    remarks: str


class ModelStats(Model):
    calls: int
    fallbacks: int
    p50_ms: float
    errors: int


class LlmStats(Model):
    calls: int
    by_model: dict[str, ModelStats]


class ErrorBody(Model):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(Model):
    error: ErrorBody


# ---------------- request bodies ----------------
class AnswersRequest(Model):
    answers: dict[str, str | int | float | bool | None]


class DraftUpdateRequest(Model):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=6000)


class PrefillRequest(Model):
    approved: bool | None = None
    portal: PortalMode = "sandbox"


class SubmittedRequest(Model):
    ack_number: str = Field(min_length=3, max_length=64)
    submitted_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class CheckStatusRequest(Model):
    portal: PortalMode | None = None


class CloseRequest(Model):
    reason: Literal["resolved", "abandoned"]


class ClockRequest(Model):
    advance_days: int | None = Field(default=None, ge=-3650, le=3650)
    reset: bool | None = None


class SandboxAttemptRequest(Model):
    session_id: str = Field(min_length=1, max_length=128)
    kind: Literal["form_opened", "field_changed", "review_reached", "submit_clicked"]


class CreateCaseForm(Model):
    """Documents the multipart body of POST /api/cases (text, language, files[])."""
    text: str = Field(min_length=10, max_length=4000)
    language: Language | None = None
    files: list[bytes] = Field(default_factory=list, description="0-3 images (jpeg/png/webp, <=5 MB each)")
