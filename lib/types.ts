export type Language = "en" | "hi" | "hinglish";
export type Freshness = "live" | "cached" | "stale" | "seed";
export type StepStatus = "locked" | "open" | "filling" | "review_ready" | "blocked" | "submitted" | "waiting" | "due" | "done" | "skipped" | "expired";
export type Blocker = "login" | "otp" | "captcha" | "portal_down" | "form_not_found" | "bot_challenge";

export interface RuleRef {
  rule_id: string;
  freshness: Freshness;
  source_url: string | null;
  source_domain: string | null;
  source_title: string | null;
  fetched_at: string | null;
  evidence_snippet: string | null;
}

export interface Draft {
  subject: string;
  body: string;
  placeholders_to_fill: string[];
  attachments_to_mention: string[];
  language: Language;
  word_count: number;
  safety: { ok: boolean; issues: { type: string; quote: string; fix: string }[] };
  edited_by_user: boolean;
  updated_at: string;
}

export interface ReviewField { label: string; value: string | null; filled: boolean; source: string | null }
export interface ReviewPacket {
  reached_review_screen: boolean;
  stopped_before_submit: boolean;
  safety_flagged: boolean;
  portal_mode: "sandbox" | "live";
  portal_url: string;
  page_url: string | null;
  fields: ReviewField[];
  fields_missing: string[];
  blocker: Blocker | null;
  blocker_message: string | null;
  notes: string | null;
  screenshots: string[];
  video_url: string | null;
  generated_at: string;
}

export interface StatusCheck {
  checked_at: string; found: boolean; status_text: string | null;
  normalized_status: "received" | "in_progress" | "replied" | "closed" | "rejected" | "unknown";
  last_updated: string | null; remarks: string | null; blocker: Blocker | null;
}

export interface Step {
  ordinal: number;
  forum: { id: string; name: string; name_hi: string; kind: string; official_url: string | null; filing_url: string | null; track_url: string | null; sector: string };
  action: string; action_hi: string; why: string; why_hi: string; status: StepStatus;
  opens_at: string | null; closes_at: string | null; opens_when: string | null; due_at: string | null;
  days_until_open: number | null; days_until_close: number | null; needs_verification: boolean;
  rule: RuleRef | null; grievance_route: { grievance_form_url: string | null; grievance_email: string | null; nodal_officer_name: string | null; escalation_matrix: { level: string; contact: string }[]; page_url: string | null; evidence_quote: string | null; found_via: string; checked_at: string } | null;
  draft: Draft | null; latest_run: { id: string; kind: string; status: string; step_ordinal: number | null; tinyfish_run_id: string | null; streaming_url: string | null; video_url: string | null; started_at: string | null; ended_at: string | null; events_count: number; error: { code: string; message: string; retryable: boolean } | null } | null;
  review_packet: ReviewPacket | null; ack_number: string | null; submitted_at: string | null; status_checks: StatusCheck[];
}

export interface Question {
  field: string; question: string; question_hi: string; input: "date" | "number" | "text" | "select" | "boolean";
  options?: { value: string; label: string; label_hi: string }[];
}

export interface CaseRecord {
  id: string; created_at: string; updated_at: string;
  state: "NEW" | "INTAKE_DONE" | "LADDER_READY" | "AWAITING_APPROVAL" | "FILLING" | "REVIEW_READY" | "SUBMITTED_BY_USER" | "WAITING" | "DUE" | "ESCALATION_READY" | "RESOLVED" | "CLOSED" | "BLOCKED" | "FAILED";
  language: Language;
  case_json: {
    language: Language; category: string; summary: string; amount_inr: number | null; incident_date: string | null;
    counterparty: { name: string | null; type: string | null }; reference_numbers: string[];
    prior_contact: { contacted_company: boolean | null; date: string | null; complaint_number: string | null; got_reply: boolean | null; reply_date: string | null; satisfied_with_reply: boolean | null };
    desired_outcome: string | null; evidence_found: string[]; missing_fields: string[]; pii_flags: string[];
  };
  missing_fields: string[]; questions: Question[]; steps: Step[]; warnings: string[];
  timeline: { at: string; type: string; title: string; title_hi: string; detail: string | null }[];
  disclaimer: string;
}

export interface CaseSummary { id: string; created_at: string; state: string; summary: string; counterparty_name: string | null; amount_inr: number | null; next_deadline: string | null; current_step: number | null }
export interface DemoClock { now: string; today: string; offset_days: number; simulated: boolean }
export interface Scenario { id: string; title: string; title_hi: string; language: Language; text: string; image_url: string | null }
export interface EscalationPack { recommendation: "close" | "escalate" | "wait_more" | "needs_user_input"; next_forum_id: string | null; filing_deadline: string | null; reasoning: string; evidence_pack_checklist: string[]; needs_verification: boolean; draft: Draft | null }
export interface ApiEvent { id: number; case_id: string; type: string; at: string; payload: Record<string, unknown> }
