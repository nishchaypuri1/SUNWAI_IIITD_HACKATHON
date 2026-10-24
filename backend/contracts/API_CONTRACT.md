# SUNWAI — Shared API Contract (v1.0, frozen for the hackathon)

> This file is the single agreement between the backend (Claude Code) and the frontend (Codex).
> Commit it at `contracts/API_CONTRACT.md`. **Neither side changes it alone.** Any change: edit this file in a PR, bump the version, tell the other side.
> Backend must make FastAPI's `/openapi.json` match this file. Frontend may generate types from it with `openapi-typescript`, but the TypeScript in §3 is the reference.

---

## 1. Conventions

- Base URL: `http://localhost:8000` (frontend reads `NEXT_PUBLIC_API_BASE_URL`). All routes start with `/api`.
- JSON everywhere, `snake_case` keys. Datetimes ISO 8601 with offset (`2026-10-24T10:56:00+05:30`). Dates `YYYY-MM-DD`.
- All date maths happens in **Asia/Kolkata**. "Today" is the **demo clock** (`GET /api/demo/clock`), never the browser clock.
- Case ids and run ids are short URL-safe strings (`cs_8f3k2m`, `run_x91p`). Step is addressed by `ordinal` (1-based).
- CORS: backend allows `http://localhost:3000` and the deployed frontend origin (env `CORS_ORIGINS`).
- No auth for the MVP (single demo user). Do not build login.

### 1.1 Error format (every non-2xx)
```json
{ "error": { "code": "ILLEGAL_TRANSITION", "message": "Step 1 is not ready for pre-fill.", "details": {} } }
```
| HTTP | code | When |
|---|---|---|
| 400 | `APPROVAL_REQUIRED` | `prefill` called without `approved: true` |
| 400 | `BAD_REQUEST` | malformed input not covered by 422 |
| 404 | `NOT_FOUND` | unknown case / step / run / forum |
| 409 | `ILLEGAL_TRANSITION` | state machine forbids the action |
| 409 | `PORTAL_BUSY` | another run is active on the same portal |
| 413 | `FILE_TOO_LARGE` | upload > 5 MB |
| 415 | `UNSUPPORTED_FILE` | not jpeg/png/webp |
| 422 | `VALIDATION_ERROR` | schema validation failed (`details.fields`) |
| 429 | `RATE_LIMITED` | our own limiter |
| 500 | `TINYFISH_CONFIG` | missing/invalid TinyFish key |
| 503 | `LLM_UNAVAILABLE` | all models in the fallback chain failed |
| 503 | `TINYFISH_UNAVAILABLE` | TinyFish down after retry |
| 500 | `INTERNAL` | anything else (never leak stack traces) |

---

## 2. Enums

```ts
type Language = "en" | "hi" | "hinglish";
type Category = "bank_payment" | "ecommerce_refund" | "travel" | "telecom" | "insurance" | "other";
type CounterpartyType = "bank" | "payment_app" | "merchant" | "airline" | "telco" | "insurer" | "other";
type DesiredOutcome = "refund" | "reversal" | "replacement" | "apology" | "other";

type CaseState =
  | "NEW" | "INTAKE_DONE" | "LADDER_READY" | "AWAITING_APPROVAL" | "FILLING" | "REVIEW_READY"
  | "SUBMITTED_BY_USER" | "WAITING" | "DUE" | "ESCALATION_READY" | "RESOLVED" | "CLOSED"
  | "BLOCKED" | "FAILED";

type StepStatus =
  | "locked"        // a previous step must happen first
  | "open"          // can be drafted / pre-filled now
  | "filling"       // agent run in progress
  | "review_ready"  // agent stopped at review screen; user must submit on the portal
  | "blocked"       // login / otp / captcha / portal down -> user continues by hand
  | "submitted"     // user entered an acknowledgement number
  | "waiting"       // clock running
  | "due"           // waiting period over; next step can open
  | "done"          // resolved at this step
  | "skipped"       // not needed (e.g. already done before Sunwai)
  | "expired";      // filing window passed

type Blocker = "login" | "otp" | "captcha" | "portal_down" | "form_not_found" | "bot_challenge";
type RunKind = "fill" | "status" | "discover" | "rule_refresh";
type RunStatus = "queued" | "running" | "completed" | "failed" | "blocked" | "safety_flagged" | "cancelled";
type NormalizedStatus = "received" | "in_progress" | "replied" | "closed" | "rejected" | "unknown";
type RuleFreshness = "live" | "cached" | "stale" | "seed";   // live = fetched < 24h ago this session
type PortalMode = "sandbox" | "live";
```

---

## 3. Objects

```ts
interface CaseJson {
  language: Language;
  category: Category;
  summary: string;                         // <= 40 words, in the user's language/script
  amount_inr: number | null;
  incident_date: string | null;            // YYYY-MM-DD
  counterparty: { name: string | null; type: CounterpartyType | null };
  reference_numbers: string[];             // txn ids, order ids (masked if they look like account numbers)
  prior_contact: {
    contacted_company: boolean | null;
    date: string | null;                   // date the company received the complaint
    complaint_number: string | null;
    got_reply: boolean | null;
    reply_date: string | null;             // date of the company's last communication
    satisfied_with_reply: boolean | null;
  };
  desired_outcome: DesiredOutcome | null;
  evidence_found: string[];
  missing_fields: string[];
  pii_flags: string[];                     // e.g. "account_number_masked", "sensitive_data_in_input"
}

interface Question {                       // asked only for missing_fields, max 4
  field: string;                           // dot path in CaseJson, e.g. "prior_contact.date"
  question: string;                        // English
  question_hi: string;                     // Hindi (Devanagari)
  input: "date" | "number" | "text" | "select" | "boolean";
  options?: { value: string; label: string; label_hi: string }[];
}

interface Forum {
  id: "company_grievance" | "rbi_cms" | "nch" | "consumer_commission" | string;
  name: string; name_hi: string;
  kind: "company" | "regulator" | "helpline" | "commission";
  official_url: string | null; filing_url: string | null; track_url: string | null;
  sector: "banking" | "consumer" | "any";
}

interface RuleRef {
  rule_id: string;
  freshness: RuleFreshness;
  source_url: string | null;
  source_domain: string | null;           // "rbi.org.in"
  source_title: string | null;
  fetched_at: string | null;              // ISO datetime
  evidence_snippet: string | null;        // verbatim quote <= 25 words
}

interface Rule extends RuleRef {
  forum_id: string;
  scheme_name: string | null;
  effective_from: string | null;
  wait_days_before_escalation: number | null;
  filing_window_days: number | null;
  filing_window_counts_from: "later_of_wait_end_or_last_reply" | "company_reply" | "end_of_wait" | "incident" | "unclear";
  evidence: Record<string, string | null>; // per-field verbatim quotes
  eligibility_conditions: string[];
  exclusions: string[];
  documents_required: string[];
  unknowns: string[];
  confidence: "high" | "medium" | "low" | "seed";
  changed_from_previous: { field: string; old: string | number | null; new: string | number | null }[] | null;
  superseded_value_note: string | null;   // e.g. "2021 scheme allowed 1 year; many bank pages still show this"
}

interface Draft {
  subject: string;
  body: string;                            // <= 250 words
  placeholders_to_fill: string[];          // "[please fill: …]" items still in body
  attachments_to_mention: string[];
  language: Language;
  word_count: number;
  safety: { ok: boolean; issues: { type: "legal_advice" | "threat" | "invented_fact" | "pii" | "security_bypass"; quote: string; fix: string }[] };
  edited_by_user: boolean;
  updated_at: string;
}

interface GrievanceRoute {
  grievance_form_url: string | null;
  grievance_email: string | null;
  nodal_officer_name: string | null;
  escalation_matrix: { level: string; contact: string }[];
  page_url: string | null;
  evidence_quote: string | null;           // <= 20 words from the page
  found_via: "tinyfish_search+agent" | "seed" | "mock";
  checked_at: string;
}

interface ReviewField { label: string; value: string | null; filled: boolean; source: string | null }

interface ReviewPacket {
  reached_review_screen: boolean;
  stopped_before_submit: boolean;          // true unless safety check found a submit-like action
  safety_flagged: boolean;
  portal_mode: PortalMode;
  portal_url: string;                      // where the user should go to submit
  page_url: string | null;                 // where the agent stopped
  fields: ReviewField[];
  fields_missing: string[];
  blocker: Blocker | null;
  blocker_message: string | null;          // user-facing, localised server-side in en; frontend has hi copy
  notes: string | null;
  screenshots: string[];                   // URLs (may expire) — optional
  video_url: string | null;                // TinyFish presigned URL, expires ~15 min
  generated_at: string;
}

interface Run {
  id: string;
  kind: RunKind;
  status: RunStatus;
  step_ordinal: number | null;
  tinyfish_run_id: string | null;
  streaming_url: string | null;
  video_url: string | null;
  started_at: string | null;
  ended_at: string | null;
  events_count: number;
  error: { code: string; message: string; retryable: boolean } | null;
}

interface StatusCheck {
  checked_at: string;
  found: boolean;
  status_text: string | null;
  normalized_status: NormalizedStatus;
  last_updated: string | null;
  remarks: string | null;
  blocker: Blocker | null;
}

interface Step {
  ordinal: number;
  forum: Forum;
  action: string;   action_hi: string;
  why: string;      why_hi: string;
  status: StepStatus;
  opens_at: string | null;                 // YYYY-MM-DD; null = depends on a future event
  closes_at: string | null;                // YYYY-MM-DD; last day to file
  opens_when: string | null;               // human text when opens_at is null
  due_at: string | null;                   // when the wait after this step ends
  days_until_open: number | null;          // relative to demo clock
  days_until_close: number | null;
  needs_verification: boolean;
  rule: RuleRef | null;
  grievance_route: GrievanceRoute | null;  // only for company_grievance
  draft: Draft | null;
  latest_run: Run | null;
  review_packet: ReviewPacket | null;
  ack_number: string | null;
  submitted_at: string | null;             // YYYY-MM-DD
  status_checks: StatusCheck[];            // newest first
}

interface TimelineItem { at: string; type: string; title: string; title_hi: string; detail: string | null }

interface Case {
  id: string;
  created_at: string; updated_at: string;
  state: CaseState;
  language: Language;
  case_json: CaseJson;
  missing_fields: string[];
  questions: Question[];
  steps: Step[];                           // empty until planned
  warnings: string[];                      // e.g. "Rule not freshly verified; using seed"
  timeline: TimelineItem[];                // newest first
  disclaimer: string;                      // always present
}

interface CaseSummary {
  id: string; created_at: string; state: CaseState; summary: string;
  counterparty_name: string | null; amount_inr: number | null;
  next_deadline: string | null; current_step: number | null;
}

interface EscalationPack {
  recommendation: "close" | "escalate" | "wait_more" | "needs_user_input";
  next_forum_id: string | null;
  filing_deadline: string | null;
  reasoning: string;
  evidence_pack_checklist: string[];
  needs_verification: boolean;
  draft: Draft | null;                     // draft for the next forum when recommendation = escalate
}

interface PrefillPreview {
  portal_mode: PortalMode;
  portal_url: string;
  field_map: { label: string; value: string | null; source: string | null }[];
  draft_excerpt: string;                   // first ~200 chars
  warnings: string[];                      // e.g. "This portal usually asks for an OTP; the agent will stop there."
}

interface DemoClock { now: string; today: string; offset_days: number; simulated: boolean }

interface Health {
  ok: boolean; mock_mode: boolean; version: string;
  tinyfish: "ok" | "missing_key" | "error";
  models: Record<"intake" | "reason" | "fast", { primary: string; available: boolean }>;
}
```

The disclaimer string (exact):
> Sunwai helps you follow the complaint procedure. It is not legal advice and does not guarantee any outcome. Please check the official portal before submitting.

Hindi (frontend renders this when language is `hi`):
> सुनवाई आपको शिकायत की प्रक्रिया समझने और उसका पालन करने में मदद करता है। यह कानूनी सलाह नहीं है और किसी नतीजे की गारंटी नहीं देता। जमा करने से पहले आधिकारिक पोर्टल पर जानकारी ज़रूर जाँचें।

---

## 4. Endpoints

| # | Method | Path | Request | Success response |
|---|---|---|---|---|
| E1 | GET | `/api/health` | — | `Health` |
| E2 | GET | `/api/demo/scenarios` | — | `{ items: { id: string; title: string; title_hi: string; language: Language; text: string; image_url: string \| null }[] }` |
| E3 | GET | `/api/demo/clock` | — | `DemoClock` |
| E4 | POST | `/api/demo/clock` | `{ advance_days: number }` or `{ reset: true }` | `DemoClock` (also emits `step_due` events if any step became due) |
| E5 | GET | `/api/forums` | — | `{ items: Forum[] }` |
| E6 | GET | `/api/cases` | — | `{ items: CaseSummary[] }` |
| E7 | POST | `/api/cases` | **multipart**: `text` (required, 10–4000 chars), `language` (optional `Language`), `files` (0–3 images, jpeg/png/webp, ≤5 MB each) | **201** `Case` (state `INTAKE_DONE`, `steps: []`) |
| E8 | POST | `/api/cases/{id}/answers` | `{ answers: Record<string, string \| number \| boolean> }` (keys are `Question.field`) | `Case` |
| E9 | POST | `/api/cases/{id}/plan` | — | `Case` (state `LADDER_READY`, `steps` filled) |
| E10 | GET | `/api/cases/{id}` | — | `Case` |
| E11 | POST | `/api/cases/{id}/steps/{n}/discover` | — | **202** `{ run_id: string }` — finds the company's grievance route (TinyFish Search + Agent G3). Result arrives as `grievance_route_found`. Only valid for `company_grievance` steps. |
| E12 | POST | `/api/cases/{id}/steps/{n}/draft` | — | `Draft` (generated, safety-checked) |
| E13 | PUT | `/api/cases/{id}/steps/{n}/draft` | `{ subject: string; body: string }` | `Draft` (re-checked, `edited_by_user: true`) |
| E14 | GET | `/api/cases/{id}/steps/{n}/prefill/preview?portal=sandbox\|live` | — | `PrefillPreview` |
| E15 | POST | `/api/cases/{id}/steps/{n}/prefill` | `{ approved: true, portal: PortalMode }` | **202** `{ run_id: string }` |
| E16 | GET | `/api/runs/{run_id}` | — | `Run & { events: { seq: number; tf_type: string; message: string; at: string }[] }` |
| E17 | POST | `/api/runs/{run_id}/cancel` | — | `{ ok: true }` |
| E18 | POST | `/api/cases/{id}/steps/{n}/submitted` | `{ ack_number: string (3–64 chars); submitted_at: string (YYYY-MM-DD, not in the future) }` | `Case` (step `waiting`, clock started) |
| E19 | POST | `/api/cases/{id}/steps/{n}/check-status` | `{ portal?: PortalMode }` | **202** `{ run_id: string }` |
| E20 | POST | `/api/cases/{id}/steps/{n}/prepare-next` | — | `EscalationPack` |
| E21 | POST | `/api/cases/{id}/close` | `{ reason: "resolved" \| "abandoned" }` | `Case` |
| E22 | GET | `/api/cases/{id}/events` | SSE, supports `Last-Event-ID` header and `?since=<id>` | `text/event-stream` (§5) |
| E23 | GET | `/api/rules/{forum_id}` | — | `Rule` |
| E24 | POST | `/api/rules/{forum_id}/refresh` | — | **202** `{ run_id: string }` (emits `rule_changed` if values changed) |
| E25 | GET | `/api/cases/{id}/evidence-pack` | `?format=md\|pdf` (pdf is stretch) | file download |
| E26 | GET | `/api/debug/llm-stats` | — | `{ calls: number; by_model: Record<string, { calls: number; fallbacks: number; p50_ms: number; errors: number }> }` |
| S1 | POST | `/api/sandbox/attempts` | `{ session_id: string; kind: "form_opened" \| "field_changed" \| "review_reached" \| "submit_clicked" }` | `{ ok: true }` |
| S2 | GET | `/api/sandbox/attempts` | — | `{ review_reached: number; submit_clicked: number; items: { session_id: string; kind: string; at: string }[] }` |
| S3 | DELETE | `/api/sandbox/attempts` | — | `{ ok: true }` |
| S4 | GET | `/api/sandbox/status/{complaint_number}` | — | `{ complaint_number: string; status_text: string; last_updated: string; remarks: string }` (deterministic fake status for G2 demo) |

### 4.1 State rules the frontend relies on
- `prefill` allowed only when step status is `open` or `blocked` (retry) and no other run is active on that portal.
- `submitted` allowed only when step status is `review_ready` or `blocked` (user filed by hand). **Only a human request to E18 can set `submitted`.** Agent output never does.
- `prepare-next` allowed only when step status is `due`, or `waiting` with a status check showing `replied`/`rejected`.
- Anything else → `409 ILLEGAL_TRANSITION`.

---

## 5. Server-Sent Events (`GET /api/cases/{id}/events`)

Wire format (one event per message, blank line between):
```
id: 42
event: agent_event
data: {"id":42,"case_id":"cs_8f3k2m","type":"agent_event","at":"2026-10-24T11:02:13+05:30","payload":{...}}

```
- Server sends a comment line `: ping` every 15 s.
- On connect, server replays events with `id > Last-Event-ID` (or `since`) from the DB, then streams live.
- The frontend must de-duplicate by `id`.

| `type` | `payload` | UI meaning |
|---|---|---|
| `case_updated` | `{ state: CaseState }` | refetch case |
| `draft_ready` | `{ step_ordinal: number }` | refetch case |
| `run_started` | `{ run_id, kind: RunKind, step_ordinal, portal_url, portal_mode }` | open agent panel |
| `streaming_url` | `{ run_id, streaming_url }` | show live browser iframe |
| `agent_event` | `{ run_id, seq: number, tf_type: "STARTED" \| "PROGRESS" \| "TF_API_RESULT" \| "COMPLETE" \| string, message: string }` | append to activity feed (HEARTBEAT is never forwarded) |
| `grievance_route_found` | `{ step_ordinal, grievance_route: GrievanceRoute }` | show route card |
| `blocker` | `{ run_id, step_ordinal, blocker: Blocker, message: string, portal_url: string }` | show hand-off card |
| `review_ready` | `{ run_id, step_ordinal, review_packet: ReviewPacket }` | show review packet + "stopped before submit" moment |
| `safety_flagged` | `{ run_id, step_ordinal, reason: string, evidence: string }` | red alert; never hide it |
| `run_failed` | `{ run_id, error_code: string, message: string, retryable: boolean }` | error card with retry |
| `run_completed` | `{ run_id, kind: RunKind }` | refetch case |
| `status_checked` | `{ step_ordinal, status_check: StatusCheck }` | update status chip |
| `step_due` | `{ step_ordinal, due_at: string }` | show "Prepare next filing" |
| `rule_changed` | `{ forum_id, changes: { field, old, new }[], source_url }` | show rule-changed banner |

---

## 6. Example: `POST /api/cases/{id}/plan` → `steps[1]`
```json
{
  "ordinal": 2,
  "forum": { "id": "rbi_cms", "name": "RBI Ombudsman (Complaint Management System)", "name_hi": "आरबीआई लोकपाल (शिकायत प्रबंधन प्रणाली)", "kind": "regulator", "official_url": "https://cms.rbi.org.in", "filing_url": "https://cms.rbi.org.in", "track_url": "https://cms.rbi.org.in", "sector": "banking" },
  "action": "File with the RBI Ombudsman", "action_hi": "आरबीआई लोकपाल के पास शिकायत दर्ज करें",
  "why": "The bank did not reply within 30 days, so the Ombudsman can now hear the complaint.",
  "why_hi": "बैंक ने 30 दिनों में जवाब नहीं दिया, इसलिए अब लोकपाल शिकायत सुन सकता है।",
  "status": "locked",
  "opens_at": "2026-11-01", "closes_at": "2027-01-30", "opens_when": null, "due_at": null,
  "days_until_open": 8, "days_until_close": 98, "needs_verification": false,
  "rule": { "rule_id": "rule_rbi_2026", "freshness": "live", "source_url": "https://…", "source_domain": "rbi.org.in", "source_title": "Reserve Bank – Integrated Ombudsman Scheme, 2026", "fetched_at": "2026-10-24T10:58:02+05:30", "evidence_snippet": "within 90 days from the date on which the timeline … expires or the date of the last communication … whichever is later" },
  "grievance_route": null, "draft": null, "latest_run": null, "review_packet": null,
  "ack_number": null, "submitted_at": null, "status_checks": []
}
```
(The bank received the complaint on 2026-10-02 and has not replied: wait ends 2026-11-01; window closes 90 days later on 2027-01-30.)