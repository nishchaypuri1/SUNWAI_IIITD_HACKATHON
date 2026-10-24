import { DISCLAIMER_EN, scenarios } from "./content";
import { parseCaseResponse, parseCaseSummaries, parseDemoClock } from "./schemas";
import type { ApiEvent, CaseRecord, CaseSummary, DemoClock, Draft, EscalationPack, Language, ReviewPacket, Scenario, Step } from "./types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const CASES_KEY = "sunwai.cases.v1";
const CLOCK_KEY = "sunwai.clock.v1";
const ATTEMPTS_KEY = "sunwai.sandbox.attempts.v1";
const RUN_PREF = "sunwai.runOutcome.v1";
export type RunOutcome = "success" | "otp" | "failure";

export class ApiError extends Error {
  code: string;
  retryable: boolean;
  constructor(message: string, code = "INTERNAL", retryable = false) { super(message); this.name = "ApiError"; this.code = code; this.retryable = retryable; }
}

export const isMock = () => (process.env.NEXT_PUBLIC_API_MODE || "mock") === "mock";
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const nowIso = () => new Date().toISOString();

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...init?.headers } }); }
  catch { throw new ApiError("Sunwai can’t reach the API right now. Your case is still on this page.", "API_OFFLINE", true); }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const error = payload?.error;
    throw new ApiError(error?.message || "Something went wrong. Please try again.", error?.code || "INTERNAL", [429, 500, 503].includes(response.status));
  }
  return response.json() as Promise<T>;
}

function readCases(): CaseRecord[] {
  try { return JSON.parse(localStorage.getItem(CASES_KEY) || "[]") as CaseRecord[]; } catch { return []; }
}
function writeCases(cases: CaseRecord[]) { localStorage.setItem(CASES_KEY, JSON.stringify(cases)); }
function mutateCase(id: string, update: (record: CaseRecord) => CaseRecord): CaseRecord {
  const cases = readCases(); const i = cases.findIndex((item) => item.id === id);
  if (i < 0) throw new ApiError("We couldn’t find this case. Go back to My cases and open it again.", "NOT_FOUND");
  cases[i] = update(cases[i]); cases[i].updated_at = nowIso(); writeCases(cases); return cases[i];
}
const timeline = (title: string, title_hi: string, detail: string | null = null, type = "case_updated") => ({ at: nowIso(), type, title, title_hi, detail });
const shortId = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 8)}`;

function makeCase(text: string, language: Language, images: File[] = []): CaseRecord {
  const lower = text.toLowerCase();
  const scenario = lower.includes("airline") || lower.includes("flight") || lower.includes("booking") ? "travel" : lower.includes("card") ? "bank_payment" : lower.includes("refund") && !lower.includes("upi") ? "ecommerce_refund" : "bank_payment";
  const contactName = scenario === "travel" ? "Airline" : scenario === "ecommerce_refund" ? "Online merchant" : lower.includes("bank") ? "Your bank" : "Your bank / UPI app";
  const amountMatch = text.match(/(?:₹|rs\.?\s?)([\d,]+)/i);
  const referenceMatch = text.match(/(?:UPI\/|CARD\/|AI)[\w\-/]+/i);
  const incidentDate = text.match(/\b(\d{1,2})\s+(September|October|सितंबर|अक्टूबर)\b/i);
  const dd = incidentDate ? String(incidentDate[1]).padStart(2, "0") : "30";
  const month = incidentDate?.[2]?.toLowerCase().includes("oct") || incidentDate?.[2]?.includes("अक्टूबर") ? "10" : "09";
  const sample = lower.includes("upi") || lower.includes("double debit") || lower.includes("दो बार") || lower.includes("twice");
  const summary = sample
    ? language === "hi" ? "UPI से एक ही खरीदारी के लिए दो बार पैसे कटे, लेकिन दूसरी राशि अब तक वापस नहीं मिली।" : "A UPI payment was debited twice, but the second amount has not been returned."
    : text.trim().split(/(?<=[.!?])\s+/).slice(0, 2).join(" ").split(/\s+/).slice(0, 38).join(" ").replace(/\b\d{12,16}\b/g, (digits) => `XXXX${digits.slice(-4)}`).replace(/\b[A-Z]{5}\d{4}[A-Z]\b/gi, "XXXXX0000X");
  const record: CaseRecord = {
    id: shortId("cs"), created_at: nowIso(), updated_at: nowIso(), state: "INTAKE_DONE", language,
    case_json: {
      language, category: scenario, summary,
      amount_inr: amountMatch ? Number(amountMatch[1].replace(/,/g, "")) : sample ? 1499 : null,
      incident_date: `${month === "09" ? "2026" : "2026"}-${month}-${dd}`,
      counterparty: { name: contactName, type: scenario === "travel" ? "airline" : "bank" },
      reference_numbers: referenceMatch ? [referenceMatch[0]] : ["XXXX2841"],
      prior_contact: { contacted_company: null, date: null, complaint_number: null, got_reply: null, reply_date: null, satisfied_with_reply: null },
      desired_outcome: "refund", evidence_found: images.length ? [`${images.length} screenshot${images.length > 1 ? "s" : ""} attached`] : ["Transaction reference mentioned"],
      missing_fields: ["prior_contact.contacted_company", "prior_contact.date", "prior_contact.got_reply"],
      pii_flags: /aadhaar|pan|\b\d{12}\b/i.test(text) ? ["sensitive_data_in_input"] : [],
    },
    missing_fields: ["prior_contact.contacted_company", "prior_contact.date", "prior_contact.got_reply"],
    questions: [
      { field: "prior_contact.contacted_company", question: "Have you already contacted the company?", question_hi: "क्या आपने कंपनी से पहले संपर्क किया है?", input: "boolean" },
      { field: "prior_contact.date", question: "When did they receive your complaint?", question_hi: "उन्हें शिकायत कब मिली?", input: "date" },
      { field: "prior_contact.got_reply", question: "Did the company reply?", question_hi: "क्या कंपनी ने जवाब दिया?", input: "boolean" },
    ],
    steps: [], warnings: ["This demo uses stored rule data. Check the official portal before filing."], timeline: [timeline("Case created", "मामला बनाया गया")], disclaimer: DISCLAIMER_EN,
  };
  return record;
}

function demoRule(forumId: string, snippet: string, domain: string, title: string): Step["rule"] {
  return { rule_id: forumId === "rbi_cms" ? "rule_rbi_2026_demo" : "rule_company_demo", freshness: "seed", source_url: forumId === "rbi_cms" ? "https://www.rbi.org.in/" : "https://www.rbi.org.in/", source_domain: domain, source_title: title, fetched_at: "2026-10-24T10:58:02+05:30", evidence_snippet: snippet };
}
function makeSteps(): Step[] {
  return [
    {
      ordinal: 1, forum: { id: "company_grievance", name: "Company grievance desk", name_hi: "कंपनी शिकायत अधिकारी", kind: "company", official_url: "https://www.rbi.org.in/", filing_url: "https://www.rbi.org.in/", track_url: "https://www.rbi.org.in/", sector: "banking" },
      action: "Ask the company to resolve the complaint", action_hi: "कंपनी से शिकायत हल करने को कहें", why: "The company should have the first chance to review your complaint.", why_hi: "कंपनी को पहले आपकी शिकायत देखने का मौका मिलना चाहिए।", status: "open", opens_at: "2026-10-24", closes_at: null, opens_when: null, due_at: null, days_until_open: 0, days_until_close: null, needs_verification: true,
      rule: demoRule("company_grievance", "Contact the regulated entity first and allow time for its reply.", "rbi.org.in", "Demo rule · contact the company first"),
      grievance_route: { grievance_form_url: "https://www.rbi.org.in/", grievance_email: null, nodal_officer_name: null, escalation_matrix: [], page_url: "https://www.rbi.org.in/", evidence_quote: "Stored demo route; verify the company’s official grievance page.", found_via: "seed", checked_at: "2026-10-24T10:58:02+05:30" },
      draft: null, latest_run: null, review_packet: null, ack_number: null, submitted_at: null, status_checks: [],
    },
    {
      ordinal: 2, forum: { id: "rbi_cms", name: "RBI Ombudsman · CMS", name_hi: "RBI Ombudsman · CMS", kind: "regulator", official_url: "https://cms.rbi.org.in", filing_url: "https://cms.rbi.org.in", track_url: "https://cms.rbi.org.in", sector: "banking" },
      action: "Escalate to the RBI Ombudsman", action_hi: "RBI Ombudsman तक शिकायत बढ़ाएँ", why: "If the company does not resolve the complaint in time, the next step may be available.", why_hi: "कंपनी समय पर हल न करे तो अगला कदम उपलब्ध हो सकता है।", status: "locked", opens_at: "2026-11-01", closes_at: "2027-01-30", opens_when: null, due_at: null, days_until_open: 8, days_until_close: 98, needs_verification: true,
      rule: demoRule("rbi_cms", "File within 90 days from the later of the reply or the end of the response period.", "rbi.org.in", "Integrated Ombudsman Scheme · demo reference"), grievance_route: null,
      draft: null, latest_run: null, review_packet: null, ack_number: null, submitted_at: null, status_checks: [],
    },
    {
      ordinal: 3, forum: { id: "nch", name: "National Consumer Helpline", name_hi: "राष्ट्रीय उपभोक्ता हेल्पलाइन", kind: "helpline", official_url: "https://consumerhelpline.gov.in/", filing_url: "https://consumerhelpline.gov.in/", track_url: "https://consumerhelpline.gov.in/", sector: "consumer" },
      action: "Ask the National Consumer Helpline for help", action_hi: "राष्ट्रीय उपभोक्ता हेल्पलाइन से मदद लें", why: "A helpline can help you try a consumer resolution route.", why_hi: "हेल्पलाइन उपभोक्ता समाधान का रास्ता आज़माने में मदद कर सकती है।", status: "locked", opens_at: null, closes_at: null, opens_when: "If the complaint remains unresolved", due_at: null, days_until_open: null, days_until_close: null, needs_verification: true,
      rule: demoRule("nch", "Check current helpline process and eligibility before using this route.", "consumerhelpline.gov.in", "Consumer Helpline · demo reference"), grievance_route: null,
      draft: null, latest_run: null, review_packet: null, ack_number: null, submitted_at: null, status_checks: [],
    },
  ];
}

export async function getScenarios(): Promise<Scenario[]> { if (!isMock()) return (await request<{ items: Scenario[] }>("/api/demo/scenarios")).items; return scenarios; }
export async function getHealth() { if (!isMock()) return request<{ ok: boolean; mock_mode: boolean; version: string; tinyfish: string }>("/api/health"); return { ok: true, mock_mode: true, version: "demo", tinyfish: "missing_key" }; }
export async function getClock(): Promise<DemoClock> {
  if (!isMock()) return parseDemoClock(await request<unknown>("/api/demo/clock"));
  let offset = 0; try { offset = Number(localStorage.getItem(CLOCK_KEY) || 0); } catch { /* server render */ }
  const base = new Date(Date.UTC(2026, 9, 24 + offset)); const today = base.toISOString().slice(0, 10);
  return { now: `${today}T10:00:00+05:30`, today, offset_days: offset, simulated: offset !== 0 };
}
export async function advanceClock(days: number | "reset"): Promise<DemoClock> {
  if (!isMock()) { const next = await request<DemoClock>("/api/demo/clock", { method: "POST", body: JSON.stringify(days === "reset" ? { reset: true } : { advance_days: days }) }); window.dispatchEvent(new CustomEvent("sunwai:clock", { detail: next })); return next; }
  const clock = await getClock(); const offset = days === "reset" ? 0 : clock.offset_days + days; localStorage.setItem(CLOCK_KEY, String(offset));
  const next = await getClock();
  for (const record of readCases()) {
    const changed = mutateCase(record.id, (item) => {
      for (const step of item.steps) {
        if (step.status === "waiting" && step.due_at && next.today >= step.due_at) {
          step.status = "due"; item.state = "DUE";
          const nextStep = item.steps.find((candidate) => candidate.ordinal === step.ordinal + 1); if (nextStep) nextStep.status = "open";
          item.timeline.unshift(timeline("Waiting period complete", "इंतज़ार की अवधि पूरी हुई", `${step.action} can now move to the next step.`, "step_due"));
        }
      }
      return item;
    }); void changed;
  }
  window.dispatchEvent(new CustomEvent("sunwai:clock", { detail: next }));
  return next;
}
export async function listCases(): Promise<CaseSummary[]> {
  if (!isMock()) return parseCaseSummaries((await request<{ items: unknown }>("/api/cases")).items);
  return readCases().map((item) => ({ id: item.id, created_at: item.created_at, state: item.state, summary: item.case_json.summary, counterparty_name: item.case_json.counterparty.name, amount_inr: item.case_json.amount_inr, next_deadline: item.steps.find((step) => step.status === "open" || step.status === "locked")?.closes_at || null, current_step: item.steps.find((step) => !["done", "skipped"].includes(step.status))?.ordinal || null }));
}
export async function createCase(text: string, language: Language, files: File[]): Promise<CaseRecord> {
  if (!isMock()) {
    const form = new FormData(); form.set("text", text); form.set("language", language); files.forEach((file) => form.append("files", file));
    return parseCaseResponse(await request<unknown>("/api/cases", { method: "POST", body: form })) as CaseRecord;
  }
  await wait(900); const item = makeCase(text, language, files); writeCases([item, ...readCases()]); return item;
}
export async function getCase(id: string): Promise<CaseRecord> { if (!isMock()) return parseCaseResponse(await request<unknown>(`/api/cases/${encodeURIComponent(id)}`)) as CaseRecord; await wait(120); const item = readCases().find((entry) => entry.id === id); if (!item) throw new ApiError("This case is no longer in the demo list.", "NOT_FOUND"); return item; }
export async function answerCase(id: string, answers: Record<string, string | number | boolean>): Promise<CaseRecord> {
  if (!isMock()) return parseCaseResponse(await request<unknown>(`/api/cases/${id}/answers`, { method: "POST", body: JSON.stringify({ answers }) })) as CaseRecord;
  return mutateCase(id, (item) => {
    if ("prior_contact.contacted_company" in answers) item.case_json.prior_contact.contacted_company = Boolean(answers["prior_contact.contacted_company"]);
    if (typeof answers["prior_contact.date"] === "string") item.case_json.prior_contact.date = answers["prior_contact.date"] as string;
    if ("prior_contact.got_reply" in answers) item.case_json.prior_contact.got_reply = Boolean(answers["prior_contact.got_reply"]);
    item.missing_fields = []; item.case_json.missing_fields = []; item.questions = []; return item;
  });
}
export async function planCase(id: string): Promise<CaseRecord> {
  if (!isMock()) return parseCaseResponse(await request<unknown>(`/api/cases/${id}/plan`, { method: "POST" })) as CaseRecord;
  return mutateCase(id, (item) => { item.steps = makeSteps(); item.state = "LADDER_READY"; item.timeline.unshift(timeline("Complaint plan prepared", "शिकायत की योजना तैयार")); return item; });
}
function makeDraft(item: CaseRecord): Draft {
  const company = item.case_json.counterparty.name || "the company";
  const amount = item.case_json.amount_inr ? `₹${new Intl.NumberFormat("en-IN").format(item.case_json.amount_inr)}` : "[please fill: amount]";
  const ref = item.case_json.reference_numbers[0] || "[please fill: reference number]";
  const date = item.case_json.incident_date || "[please fill: transaction date]";
  const prior = item.case_json.prior_contact.contacted_company === true
    ? `I contacted the company on ${item.case_json.prior_contact.date || "[please fill: date of first complaint]"}${item.case_json.prior_contact.got_reply === true ? ", and received a reply" : ", but have not received a reply"}.`
    : item.case_json.prior_contact.contacted_company === false ? "I have not contacted the company about this issue yet." : "[please fill: whether and when you contacted the company].";
  const body = `Dear Grievance Officer,\n\nI am writing about a payment issue with ${company}. On ${date}, ${amount} was debited from my account. The transaction reference is ${ref}. ${prior}\n\nPlease review the transaction and let me know the outcome. I can provide the available transaction record and relevant complaint correspondence.\n\nRegards,\n[please fill: your name]`;
  const wordCount = body.trim().split(/\s+/).length;
  return { subject: `Request to resolve a payment complaint · ${company}`, body, placeholders_to_fill: body.match(/\[please fill:[^\]]+\]/g) || [], attachments_to_mention: ["Transaction receipt or bank statement", "Previous complaint and reply, if any"], language: item.language, word_count: wordCount, safety: { ok: true, issues: [] }, edited_by_user: false, updated_at: nowIso() };
}
export async function generateDraft(id: string, ordinal: number): Promise<Draft> {
  if (!isMock()) return request<Draft>(`/api/cases/${id}/steps/${ordinal}/draft`, { method: "POST" });
  let result!: Draft; mutateCase(id, (item) => { const step = item.steps.find((entry) => entry.ordinal === ordinal); if (!step) throw new ApiError("Step not found.", "NOT_FOUND"); step.draft = makeDraft(item); result = step.draft; item.state = "AWAITING_APPROVAL"; return item; }); return result;
}
export async function saveDraft(id: string, ordinal: number, draft: Pick<Draft, "subject" | "body">): Promise<Draft> {
  if (!isMock()) return request<Draft>(`/api/cases/${id}/steps/${ordinal}/draft`, { method: "PUT", body: JSON.stringify(draft) });
  let saved!: Draft; mutateCase(id, (item) => { const step = item.steps.find((entry) => entry.ordinal === ordinal); if (!step?.draft) throw new ApiError("Create a draft before saving.", "ILLEGAL_TRANSITION"); const bodyWords = draft.body.trim().split(/\s+/).filter(Boolean); step.draft = { ...step.draft, ...draft, word_count: bodyWords.length, placeholders_to_fill: draft.body.match(/\[please fill:[^\]]+\]/g) || [], edited_by_user: true, updated_at: nowIso() }; saved = step.draft; return item; }); return saved;
}
export async function previewPrefill(id: string, ordinal: number, portal: "sandbox" | "live") {
  if (!isMock()) return request<{ portal_mode: string; portal_url: string; field_map: { label: string; value: string | null; source: string | null }[]; draft_excerpt: string; warnings: string[] }>(`/api/cases/${id}/steps/${ordinal}/prefill/preview?portal=${portal}`);
  const item = await getCase(id); const step = item.steps.find((entry) => entry.ordinal === ordinal)!;
  return { portal_mode: portal, portal_url: portal === "sandbox" ? `${window.location.origin}/sandbox/grievance` : step.forum.filing_url || "https://cms.rbi.org.in", field_map: [
    { label: "Transaction date", value: item.case_json.incident_date, source: "Your message" },
    { label: "Transaction reference", value: item.case_json.reference_numbers[0] || null, source: "Your message" },
    { label: "Amount", value: item.case_json.amount_inr ? `₹${new Intl.NumberFormat("en-IN").format(item.case_json.amount_inr)}` : null, source: "Your message" },
    { label: "Complaint details", value: step.draft?.body || null, source: "Your draft" },
  ], draft_excerpt: step.draft?.body.slice(0, 200) || "", warnings: ["The portal may ask for an OTP. The agent will stop and hand the form back to you."] };
}
export async function startPrefill(id: string, ordinal: number, portal: "sandbox" | "live") {
  if (!isMock()) return request<{ run_id: string }>(`/api/cases/${id}/steps/${ordinal}/prefill`, { method: "POST", body: JSON.stringify({ approved: true, portal }) });
  localStorage.setItem(RUN_PREF, getRunOutcome());
  mutateCase(id, (item) => { const step = item.steps.find((entry) => entry.ordinal === ordinal)!; step.status = "filling"; step.latest_run = { id: shortId("run"), kind: "fill", status: "running", step_ordinal: ordinal, tinyfish_run_id: null, streaming_url: null, video_url: null, started_at: nowIso(), ended_at: null, events_count: 0, error: null }; item.state = "FILLING"; item.timeline.unshift(timeline("Agent started pre-filling", "एजेंट ने फ़ॉर्म भरना शुरू किया")); return item; });
  return { run_id: shortId("run") };
}
export async function finishMockRun(id: string, ordinal: number, outcome: RunOutcome, portal: "sandbox" | "live") {
  if (!isMock()) return getCase(id);
  const item = await getCase(id); const step = item.steps.find((entry) => entry.ordinal === ordinal)!;
  if (outcome === "success") {
    if (portal === "sandbox") await recordSandboxAttempt(id, "review_reached");
    const packet: ReviewPacket = { reached_review_screen: true, stopped_before_submit: true, safety_flagged: false, portal_mode: portal, portal_url: portal === "sandbox" ? `${window.location.origin}/sandbox/grievance?session=${encodeURIComponent(id)}` : step.forum.filing_url || "https://cms.rbi.org.in", page_url: portal === "sandbox" ? `${window.location.origin}/sandbox/grievance?session=${encodeURIComponent(id)}&review=1` : step.forum.filing_url || "https://cms.rbi.org.in", fields: [
      { label: "Complaint category", value: "UPI / payment", filled: true, source: "Your complaint" }, { label: "Transaction date", value: item.case_json.incident_date || "30/09/2026", filled: true, source: "Your message" }, { label: "Transaction reference", value: item.case_json.reference_numbers[0] || "XXXX2841", filled: true, source: "Your message" }, { label: "Amount", value: item.case_json.amount_inr ? `₹${new Intl.NumberFormat("en-IN").format(item.case_json.amount_inr)}` : null, filled: Boolean(item.case_json.amount_inr), source: "Your message" }, { label: "Complaint description", value: step.draft?.body || null, filled: Boolean(step.draft), source: "Your draft" },
    ], fields_missing: item.case_json.amount_inr ? [] : ["Amount"], blocker: null, blocker_message: null, notes: "The review page is ready. Sunwai did not press Submit.", screenshots: [], video_url: null, generated_at: nowIso() };
    return mutateCase(id, (record) => { const current = record.steps.find((entry) => entry.ordinal === ordinal)!; current.status = "review_ready"; current.review_packet = packet; if (current.latest_run) { current.latest_run.status = "completed"; current.latest_run.ended_at = nowIso(); current.latest_run.events_count = 8; } record.state = "REVIEW_READY"; record.timeline.unshift(timeline("Agent stopped at the review screen", "एजेंट जाँच वाले पेज पर रुका")); return record; });
  }
  if (outcome === "otp") return mutateCase(id, (record) => { const current = record.steps.find((entry) => entry.ordinal === ordinal)!; current.status = "blocked"; current.review_packet = { reached_review_screen: false, stopped_before_submit: true, safety_flagged: false, portal_mode: portal, portal_url: portal === "sandbox" ? `${window.location.origin}/sandbox/grievance` : current.forum.filing_url || "https://cms.rbi.org.in", page_url: null, fields: [], fields_missing: [], blocker: "otp", blocker_message: "This portal needs a one-time password sent to your phone or email.", notes: null, screenshots: [], video_url: null, generated_at: nowIso() }; if (current.latest_run) { current.latest_run.status = "blocked"; current.latest_run.ended_at = nowIso(); } record.state = "BLOCKED"; record.timeline.unshift(timeline("Agent handed the portal back for OTP", "OTP के लिए एजेंट ने पोर्टल आपको सौंपा")); return record; });
  return mutateCase(id, (record) => { const current = record.steps.find((entry) => entry.ordinal === ordinal)!; current.status = "open"; if (current.latest_run) { current.latest_run.status = "failed"; current.latest_run.ended_at = nowIso(); current.latest_run.error = { code: "TINYFISH_UNAVAILABLE", message: "The demo agent stopped before it could prepare the form.", retryable: true }; } record.state = "FAILED"; record.timeline.unshift(timeline("Agent could not finish this run", "एजेंट यह रन पूरा नहीं कर सका")); return record; });
}
export function getRunOutcome(): RunOutcome { try { const value = localStorage.getItem(RUN_PREF); return value === "otp" || value === "failure" ? value : "success"; } catch { return "success"; } }
export function setRunOutcome(value: RunOutcome) { try { localStorage.setItem(RUN_PREF, value); } catch { /* storage can be disabled */ } }
export async function cancelRun(runId: string | null) { if (!runId || isMock()) return { ok: true }; return request<{ ok: boolean }>(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }); }
export async function recordSubmitted(id: string, ordinal: number, ack: string, submittedAt: string): Promise<CaseRecord> {
  if (!isMock()) return parseCaseResponse(await request<unknown>(`/api/cases/${id}/steps/${ordinal}/submitted`, { method: "POST", body: JSON.stringify({ ack_number: ack.trim(), submitted_at: submittedAt }) })) as CaseRecord;
  const [year, month, day] = submittedAt.split("-").map(Number); const date = new Date(Date.UTC(year, month - 1, day + 30)); const dueAt = date.toISOString().slice(0, 10);
  return mutateCase(id, (item) => { const step = item.steps.find((entry) => entry.ordinal === ordinal)!; step.status = "waiting"; step.ack_number = ack.trim(); step.submitted_at = submittedAt; step.due_at = dueAt; if (step.forum.kind === "company") { item.case_json.prior_contact.contacted_company = true; item.case_json.prior_contact.date = submittedAt; item.case_json.prior_contact.complaint_number = ack.trim(); } item.state = "WAITING"; item.timeline.unshift(timeline("You recorded a filing", "आपने शिकायत जमा करना दर्ज किया", `Acknowledgement ${ack.trim()}`)); return item; });
}
export async function checkStatus(id: string, ordinal: number, portal: "sandbox" | "live" = "sandbox"): Promise<{ run_id?: string; case?: CaseRecord }> {
  if (!isMock()) return request<{ run_id: string }>(`/api/cases/${id}/steps/${ordinal}/check-status`, { method: "POST", body: JSON.stringify({ portal }) });
  const checked: CaseRecord = mutateCase(id, (item) => { const step = item.steps.find((entry) => entry.ordinal === ordinal)!; step.status_checks.unshift({ checked_at: nowIso(), found: true, status_text: "Your complaint has been received and is under review.", normalized_status: "in_progress", last_updated: "2026-10-24", remarks: "This is a deterministic demo status.", blocker: null }); item.timeline.unshift(timeline("Status checked", "स्थिति जाँची गई")); return item; }); return { case: checked };
}
export async function prepareNext(id: string, ordinal: number): Promise<EscalationPack> {
  if (!isMock()) return request<EscalationPack>(`/api/cases/${id}/steps/${ordinal}/prepare-next`, { method: "POST" });
  const item = await getCase(id); const filedStep = item.steps.find((step) => step.ordinal === ordinal); const nextStep = item.steps.find((step) => step.ordinal === ordinal + 1);
  const priorContact = item.case_json.prior_contact;
  if (nextStep && (priorContact.contacted_company !== true || !priorContact.date || !filedStep?.ack_number)) {
    return { recommendation: "needs_user_input", next_forum_id: null, filing_deadline: null, reasoning: "Record the company complaint date and acknowledgement, then check the current scheme and eligibility before preparing another filing.", evidence_pack_checklist: [], needs_verification: true, draft: null };
  }
  let nextDraft: Draft | null = null;
  if (nextStep) {
    const company = item.case_json.counterparty.name || "the company";
    const amount = item.case_json.amount_inr ? `₹${new Intl.NumberFormat("en-IN").format(item.case_json.amount_inr)}` : "[please fill: amount]";
    const reference = item.case_json.reference_numbers[0] || "[please fill: transaction reference]";
    const complaintDate = item.case_json.prior_contact.date || "[please fill: company complaint date]";
    const ack = filedStep?.ack_number || "[please fill: company acknowledgement number]";
    const body = `Dear Sir or Madam,\n\nI am asking for review of an unresolved payment complaint involving ${company}. On ${item.case_json.incident_date || "[please fill: transaction date]"}, ${amount} was debited. Transaction reference: ${reference}.\n\nI contacted ${company} on ${complaintDate}. The company complaint acknowledgement is ${ack}. ${item.case_json.prior_contact.got_reply === true ? "The reply did not resolve the issue." : "I have not received a reply that resolved the issue."}\n\nPlease review the complaint under the applicable scheme. I can provide the transaction record and earlier correspondence.\n\nRegards,\n[please fill: your name]`;
    nextDraft = { subject: `Unresolved payment complaint · ${company}`, body, placeholders_to_fill: body.match(/\[please fill:[^\]]+\]/g) || [], attachments_to_mention: ["Original complaint and acknowledgement", "Transaction record", "Company reply or proof no reply arrived"], language: item.language, word_count: body.trim().split(/\s+/).length, safety: { ok: true, issues: [] }, edited_by_user: false, updated_at: nowIso() };
    mutateCase(id, (record) => { const step = record.steps.find((entry) => entry.ordinal === ordinal + 1); if (step) step.draft = nextDraft; record.state = "ESCALATION_READY"; record.timeline.unshift(timeline("Next filing draft prepared", "अगली शिकायत का मसौदा तैयार")); return record; });
  }
  return { recommendation: "escalate", next_forum_id: nextStep?.forum.id || null, filing_deadline: nextStep?.closes_at || "2027-01-30", reasoning: "The waiting period is over in this simulated demo. Check the official scheme and your eligibility before filing.", evidence_pack_checklist: ["Copy of your original complaint", "Acknowledgement number", "Company reply or proof that no reply arrived", "Transaction record"], needs_verification: true, draft: nextDraft };
}
export async function discoverRoute(id: string, ordinal: number) { if (!isMock()) return request<{ run_id: string }>(`/api/cases/${id}/steps/${ordinal}/discover`, { method: "POST" }); await wait(400); return mutateCase(id, (item) => { const step = item.steps.find((entry) => entry.ordinal === ordinal)!; if (step.grievance_route) { step.grievance_route.found_via = "mock"; step.grievance_route.checked_at = nowIso(); } return item; }); }
export async function closeCase(id: string, reason: "resolved" | "abandoned") { if (!isMock()) return parseCaseResponse(await request<unknown>(`/api/cases/${id}/close`, { method: "POST", body: JSON.stringify({ reason }) })) as CaseRecord; return mutateCase(id, (item) => { item.state = reason === "resolved" ? "RESOLVED" : "CLOSED"; item.timeline.unshift(timeline(reason === "resolved" ? "Case marked resolved" : "Case closed", reason === "resolved" ? "मामला हल हुआ" : "मामला बंद किया गया")); return item; }); }

export interface SandboxAttempt { session_id: string; kind: "form_opened" | "field_changed" | "review_reached" | "submit_clicked"; at: string }
function getAttempts(): SandboxAttempt[] { try { return JSON.parse(localStorage.getItem(ATTEMPTS_KEY) || "[]") as SandboxAttempt[]; } catch { return []; } }
export async function recordSandboxAttempt(session: string, kind: SandboxAttempt["kind"]) { if (!isMock()) return request<{ ok: boolean }>("/api/sandbox/attempts", { method: "POST", body: JSON.stringify({ session_id: session, kind }) }); const items = getAttempts(); if (kind !== "field_changed" || items.at(-1)?.kind !== kind) items.push({ session_id: session, kind, at: nowIso() }); localStorage.setItem(ATTEMPTS_KEY, JSON.stringify(items)); window.dispatchEvent(new CustomEvent("sunwai:sandbox-attempts")); return { ok: true }; }
export async function getSandboxAttempts() { if (!isMock()) return request<{ review_reached: number; submit_clicked: number; items: SandboxAttempt[] }>("/api/sandbox/attempts"); const items = getAttempts(); return { review_reached: items.filter((item) => item.kind === "review_reached").length, submit_clicked: items.filter((item) => item.kind === "submit_clicked").length, items }; }
export async function resetSandboxAttempts() { if (!isMock()) return request<{ ok: boolean }>("/api/sandbox/attempts", { method: "DELETE" }); localStorage.removeItem(ATTEMPTS_KEY); return { ok: true }; }
export async function sandboxStatus(number: string) { if (!isMock()) return request<{ complaint_number: string; status_text: string; last_updated: string; remarks: string }>(`/api/sandbox/status/${encodeURIComponent(number)}`); await wait(250); return { complaint_number: number, status_text: "Complaint received · under review", last_updated: "24 Oct 2026", remarks: "This is a deterministic demo status. No complaint was sent to a real company." }; }
export async function downloadEvidence(id: string, format: "md" | "pdf" = "md") { if (!isMock()) { window.open(`${API_BASE}/api/cases/${id}/evidence-pack?format=${format}`, "_blank", "noopener,noreferrer"); return; } const item = await getCase(id); const content = `# Sunwai evidence pack\n\n${item.case_json.summary}\n\nCompany: ${item.case_json.counterparty.name || "Not provided"}\nAmount: ${item.case_json.amount_inr ? `₹${new Intl.NumberFormat("en-IN").format(item.case_json.amount_inr)}` : "Not provided"}\n\n${item.timeline.map((entry) => `- ${entry.at}: ${entry.title}`).join("\n")}\n\n${DISCLAIMER_EN}`; const blob = new Blob([content], { type: "text/markdown;charset=utf-8" }); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `sunwai-${item.id}-evidence.md`; link.click(); URL.revokeObjectURL(url); }

export function connectCaseEvents(caseId: string, onEvent: (event: ApiEvent) => void, onStatus?: (status: "connected" | "reconnecting") => void) {
  if (isMock() || typeof EventSource === "undefined") return () => undefined;
  let lastId = 0; const eventNames = ["case_updated", "draft_ready", "run_started", "streaming_url", "agent_event", "grievance_route_found", "blocker", "review_ready", "safety_flagged", "run_failed", "run_completed", "status_checked", "step_due", "rule_changed"];
  let closed = false; let source: EventSource | null = null;
  const connect = () => { if (closed) return; source = new EventSource(`${API_BASE}/api/cases/${caseId}/events?since=${lastId}`); source.onopen = () => onStatus?.("connected"); source.onerror = () => { onStatus?.("reconnecting"); source?.close(); window.setTimeout(connect, 1500); }; for (const name of eventNames) source.addEventListener(name, (event) => { const message = event as MessageEvent<string>; const id = Number(message.lastEventId || 0); if (id && id <= lastId) return; if (id) lastId = id; try { const payload = JSON.parse(message.data) as ApiEvent; if (!payload.type) payload.type = name; onEvent(payload); } catch { /* ignore malformed event; the next replay remains available */ } }); };
  connect(); return () => { closed = true; source?.close(); };
}

export async function listForums() { if (!isMock()) return request<{ items: unknown[] }>("/api/forums"); return { items: [] }; }
export async function getRule(forumId: string) { if (!isMock()) return request<unknown>(`/api/rules/${forumId}`); return null; }
export async function refreshRule(forumId: string) { if (!isMock()) return request<{ run_id: string }>(`/api/rules/${forumId}/refresh`, { method: "POST" }); return { run_id: shortId("run") }; }
