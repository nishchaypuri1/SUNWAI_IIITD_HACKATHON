# Connecting the frontend to the Sunwai backend

The backend implements `contracts/API_CONTRACT.md` v1.0 exactly. This page is the practical wiring guide
(hand it to Codex together with the contract).

## 1. Run the backend

```bash
cd api
uv sync
cp ../.env.example ../.env          # MOCK_MODE=1 works with no keys at all
uv run uvicorn app.main:app --reload --port 8000
```

- Swagger UI: http://localhost:8000/docs · OpenAPI: http://localhost:8000/openapi.json (also committed at
  `contracts/openapi.json`; regenerate with `make openapi`).
- Frontend env: `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`, `NEXT_PUBLIC_API_MODE=live`.
- CORS: the backend allows the origins in `CORS_ORIGINS` (default `http://localhost:3000`). Add your Vercel origin
  there, comma-separated, exact scheme + host.
- Types: the TypeScript in the contract §3 is the reference. Generated alternative:
  `pnpm exec openapi-typescript http://localhost:8000/openapi.json -o lib/api/openapi.d.ts`.

## 2. Conventions you can rely on

- All JSON is `snake_case`; dates `YYYY-MM-DD`; datetimes ISO with `+05:30`.
- "Today" = `GET /api/demo/clock` (`today`), never the browser clock. `days_until_open` / `days_until_close` are
  already computed against it.
- Every non-2xx body is `{ "error": { "code", "message", "details" } }`; `message` is safe to show to users.
  Validation errors (422) list `details.fields[] = { field, message }`.
- `amount_inr` is a JSON number and may arrive as `1499.0`.
- Every `Case` has `disclaimer` (English). Show the Hindi one from the contract when the UI language is Hindi.

## 3. The demo flow, call by call

| UI moment | Call | Then |
|---|---|---|
| Pick a sample | `GET /api/demo/scenarios` | prefill the textarea |
| Submit the problem | `POST /api/cases` (multipart: `text`, optional `language`, up to 3 `files`) | 201 `Case`; show `questions` (max 4, each with `question_hi`, `input`, `options`) |
| Answer questions | `POST /api/cases/{id}/answers` `{answers: {"prior_contact.date": "2026-10-02", ...}}` | keys are `Question.field`; booleans may be `true/false` |
| Show the ladder | `POST /api/cases/{id}/plan` | `steps[]` with dates, `rule` proof stamp (`source_url`, `fetched_at`, `evidence_snippet`, `freshness`) |
| Rule details / "rule changed" banner | `GET /api/rules/rbi_cms` | `superseded_value_note`, `changed_from_previous` |
| Find the company's grievance desk (optional) | `POST .../steps/1/discover` → 202 `{run_id}` | wait for SSE `grievance_route_found` |
| Draft | `POST .../steps/{n}/draft` → `Draft`; edit with `PUT .../draft {subject, body}` | show `safety.issues`, `placeholders_to_fill` |
| Preview before approval | `GET .../steps/{n}/prefill/preview?portal=sandbox` | show `field_map` + `warnings`; case becomes `AWAITING_APPROVAL` |
| Approve | `POST .../steps/{n}/prefill {approved: true, portal: "sandbox"}` → 202 `{run_id}` | without `approved: true` you get 400 `APPROVAL_REQUIRED` |
| Live agent panel | SSE `run_started`, `streaming_url`, `agent_event`, then `review_ready` / `blocker` / `safety_flagged` / `run_failed` | `GET /api/runs/{run_id}` gives the same feed if you reload |
| User submitted on the portal | `POST .../steps/{n}/submitted {ack_number, submitted_at}` | step → `waiting`, `due_at` set |
| Skip 30 days | `POST /api/demo/clock {advance_days: 30}` (reset: `{reset: true}`) | SSE `step_due`; case → `DUE` |
| Prepare the next filing | `POST .../steps/{n}/prepare-next` → `EscalationPack` (with `draft` for the next forum) | case → `ESCALATION_READY` |
| Status check | `POST .../steps/{n}/check-status {portal: "sandbox"}` → 202 | SSE `status_checked` |
| Download | `GET /api/cases/{id}/evidence-pack?format=md` | file download (pdf → 400 for now) |

Which buttons to enable (contract §4.1): pre-fill when step `status` is `open` or `blocked`; "I submitted" when
`review_ready` or `blocked`; "Prepare next" when `due`, or `waiting` with `status_checks[0].normalized_status` in
`replied|rejected`; status check when `submitted|waiting|due` and `ack_number` is set. Anything else returns 409.

## 4. Server-Sent Events

Events are sent with a named `event:` line, so `onmessage` will NOT fire; add a listener per type:

```ts
const TYPES = ["case_updated","draft_ready","run_started","streaming_url","agent_event","grievance_route_found",
  "blocker","review_ready","safety_flagged","run_failed","run_completed","status_checked","step_due","rule_changed"];

export function openCaseStream(api: string, caseId: string, onEvent: (e: any) => void) {
  let lastId = 0;
  const seen = new Set<number>();
  let es: EventSource;
  const connect = () => {
    es = new EventSource(`${api}/api/cases/${caseId}/events?since=${lastId}`);
    for (const t of TYPES) es.addEventListener(t, (m: MessageEvent) => {
      const evt = JSON.parse(m.data);             // {id, case_id, type, at, payload}
      if (seen.has(evt.id)) return;               // de-duplicate by id (replays happen on reconnect)
      seen.add(evt.id); lastId = Math.max(lastId, evt.id);
      onEvent(evt);
    });
    es.onerror = () => { es.close(); setTimeout(connect, 2000); };
  };
  connect();
  return () => es.close();
}
```

- On connect the server replays events with `id > since` (or `Last-Event-ID`), then streams live; `: ping` every 15 s.
- `case_id` is `null` only on `rule_changed` (global).
- Rule refresh progress (`POST /api/rules/{forum}/refresh`) is not pushed to case streams; poll `GET /api/runs/{run_id}`.

## 5. Creating a case (multipart)

```ts
const fd = new FormData();
fd.append("text", text);                 // 10–4000 chars
if (lang) fd.append("language", lang);   // "en" | "hi" | "hinglish"
for (const f of files.slice(0, 3)) fd.append("files", f);   // jpeg/png/webp, ≤5 MB each
const res = await fetch(`${API}/api/cases`, { method: "POST", body: fd });   // do not set Content-Type yourself
```
Errors: 413 `FILE_TOO_LARGE`, 415 `UNSUPPORTED_FILE`, 422 `VALIDATION_ERROR`.

## 6. The sandbox pages the agent needs (frontend owns them)

TinyFish runs in the cloud, so these pages must be on a public HTTPS URL (`SANDBOX_PUBLIC_URL` in the backend .env).

**`/sandbox/grievance?session=<run_id>`** (fictional "Kanakpur Demo Bank" form)
- Fields and labels exactly from `contracts/sandbox_fields.json` (the backend maps case data onto those labels).
- A **Review** button that shows a review screen with the entered values, then a final **Submit** button.
- Log to the backend with the `session` value: `POST /api/sandbox/attempts {session_id, kind}` for
  `form_opened` (on load), `field_changed` (debounced), `review_reached`, and `submit_clicked`.
  Submit must only log `submit_clicked` and show "Demo only — nothing was sent". A `submit_clicked` during a run
  makes the backend flag the run (`safety_flagged`), which is the proof shown to judges.

**`/sandbox/status?complaint_number=<n>&session=<run_id>`**
- A lookup box (prefilled from the query) that calls `GET /api/sandbox/status/{complaint_number}` and shows
  `status_text`, `last_updated`, `remarks`. Deterministic: numbers containing `RP` → Replied, `RJ` → Rejected,
  `CL` → Closed, anything else → Under review.

**Demo panel**: `GET /api/sandbox/attempts` for the live counters (`review_reached`, `submit_clicked`),
`DELETE /api/sandbox/attempts` to reset.

## 7. Mock vs live

- `MOCK_MODE=1` (backend): same endpoints and events; agent runs are replays of recorded streams
  (`MOCK_DELAY_SCALE=1` ≈ 20 s per fill, `0` = instant). `streaming_url` is not sent in mock mode, so fall back to
  the activity feed. Live portal mode in mock replays an OTP wall → `blocker` hand-off.
- `GET /api/health` → `mock_mode`, `tinyfish` (`ok|missing_key|error`), model availability per role.
