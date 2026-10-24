# Sunwai — backend

Sunwai turns a consumer complaint (English, Hindi or Hinglish) into an escalation ladder built from the
**live official rules**, drafts each complaint, and uses a **TinyFish web agent to pre-fill the portal form up to
the review screen and stop**. The human submits, the clock starts, the agent checks status, and when the wait
ends Sunwai prepares the next filing.

This folder contains the backend (`api/`) and the shared contract (`contracts/`). The frontend (`web/`) connects
through `contracts/API_CONTRACT.md`; see **[docs/FRONTEND_INTEGRATION.md](docs/FRONTEND_INTEGRATION.md)**.

## Quick start

```bash
cp .env.example .env            # MOCK_MODE=1: runs fully offline, no keys needed
cd api && uv sync
uv run uvicorn app.main:app --reload --port 8000
# http://localhost:8000/docs  ·  curl localhost:8000/api/health
```

Or from the repo root: `make install`, `make dev`, `make mock`, `make test`, `make eval`.
Docker: `docker compose up --build` (API on :8000, SQLite in a volume).

Try the whole flow with curl (mock mode):

```bash
API=localhost:8000
CID=$(curl -s -X POST $API/api/cases -F 'text=PhonePe se 20 Oct ko 1,499 rupaye do baar kaat liye. Abhi tak complaint nahi ki.' | jq -r .id)
curl -s -X POST $API/api/cases/$CID/plan | jq '.steps[] | {forum: .forum.id, status, opens_at, closes_at}'
curl -s $API/api/cases/$CID/steps/1/prefill/preview?portal=sandbox | jq .field_map
RUN=$(curl -s -X POST $API/api/cases/$CID/steps/1/prefill -H 'content-type: application/json' -d '{"approved":true,"portal":"sandbox"}' | jq -r .run_id)
curl -N $API/api/cases/$CID/events            # watch agent_event ... review_ready (Ctrl-C)
curl -s -X POST $API/api/cases/$CID/steps/1/submitted -H 'content-type: application/json' -d '{"ack_number":"KDB-1188","submitted_at":"2026-10-24"}' | jq .state
curl -s -X POST $API/api/demo/clock -H 'content-type: application/json' -d '{"advance_days":30}'
curl -s -X POST $API/api/cases/$CID/steps/1/prepare-next | jq '{recommendation, filing_deadline}'
```

## Modes

| Mode | What happens |
|---|---|
| `MOCK_MODE=1` | No network. LLM calls return a recorded fixture (`app/llm/fixtures/{prompt}/{sha}.json`) or the deterministic mock brain (`app/llm/mock_brain.py`). TinyFish runs replay recorded SSE streams (`app/tinyfish/fixtures/sse/`) with realistic delays (`MOCK_DELAY_SCALE`). Same code paths, same events. |
| `MOCK_MODE=0` | Live TinyFish (Search, Fetch, Agent) and live LLMs via OpenAI-compatible endpoints (OpenRouter by default). Needs `TINYFISH_API_KEY` and an LLM key. |
| `RECORD_FIXTURES=1` | With live mode, saves every LLM output and raw agent stream (`make fixtures`). |

The sandbox portal (`/sandbox/grievance`, `/sandbox/status`) is served by the frontend; set `SANDBOX_PUBLIC_URL`
to its public HTTPS URL so TinyFish can open it.

## How it works

```
POST /api/cases ─ pii.scrub ─ P1 intake ─ missing fields + questions (deterministic, en/hi)
POST /plan ─ core/ladder.py (all date maths, RB-IOS 2026) ─ P3 why-sentences (numbers checked against engine)
POST /draft ─ P4 ─ ≤250 words ─ P7 + regex safety ─ placeholders
GET  /prefill/preview ─ P5 field map onto the portal's labels
POST /prefill ─ TinyFish run-sse with G1 ("never click Submit") ─ SSE relay ─ post-run safety check ─ review packet
POST /submitted (human only) ─ clock starts ─ /demo/clock sweep ─ step_due
POST /check-status ─ G2 read-only ─ P6 normalise    POST /prepare-next ─ P9, deadline overridden by the engine
POST /rules/{forum}/refresh ─ TinyFish Search ─ Fetch (ttl=0) ─ P2 ─ every quote verified in the fetched text
```

Key files: `app/core/ladder.py` (deterministic engine), `app/core/safety.py` (submit detector, draft checks),
`app/core/pii.py`, `app/llm/gateway.py` (the only LLM caller), `app/tinyfish/client.py` (the only TinyFish caller),
`app/services/*` (one module per feature), `app/routes/*` (thin HTTP layer).

### Safety by construction

1. **Never submits.** G1 goal text + `final_submit_clicked` in the output schema + a post-run detector over every
   agent action + the sandbox's own `submit_clicked` log + the state machine (only `POST /submitted`, a human
   request, can set `submitted`). Any hit → run `safety_flagged`, step `blocked`, SSE `safety_flagged`.
2. **No invented facts.** Dates come only from `core/ladder.py`. A rule value counts as verified only if its quote
   is found in the fetched official text; otherwise the step is `needs_verification` and a warning is shown.
   P3/P9 text that introduces numbers the engine did not produce is discarded.
3. **PII minimisation.** Aadhaar, PAN, card/account numbers, phone, OTP/PIN/passwords are masked before any LLM or
   TinyFish call and before saving (test asserts the DB holds none).
4. **Untrusted content is data.** User text, pages and agent output are wrapped in tags in every prompt.
5. **One agent run per portal**, `409 PORTAL_BUSY` otherwise.

### Case state

`Case.state` follows the furthest active step: `FILLING` / `REVIEW_READY` / `BLOCKED` while a step is in that status;
otherwise the last non-locked step decides (`open` → `LADDER_READY`, `AWAITING_APPROVAL` after a preview, `DUE`
when the previous step is due, `ESCALATION_READY` after prepare-next; `waiting` → `WAITING`; `due` → `DUE`;
`done` → `RESOLVED`). `POST /close` sets `RESOLVED` or `CLOSED`.

## Tests and evaluation

```bash
cd api && uv run pytest -q        # 114 tests: ladder maths, PII, safety, SSE parser, gateway, TinyFish client,
                                  # 15 scenarios, API walkthrough, live wiring vs fake servers, no-PII-in-DB
make eval                         # writes eval/results.md — only measured numbers
```

Current `make eval` output (mock intake + engine): routing 15/15, deadlines 15/15, PII leaks 0/6. Sandbox submit
clicks, fields-correct and time-to-review are **not measured** until live sandbox runs exist (each live sandbox
pre-fill appends to `eval/live_runs.jsonl`). Routing in eval uses the mock intake; run the scenarios live after
`make fixtures` to measure the real LLM.

## Before the demo (checklist for the backend)

1. `make spike` with real keys → paste the output into `docs/VERIFIED.md`; set confirmed model ids in `.env`.
2. Deploy the sandbox pages, set `SANDBOX_PUBLIC_URL`, run 10 live sandbox pre-fills, then `make eval`.
3. `make fixtures` to record the exact demo path; rehearse once with `MOCK_MODE=1`.
4. `DELETE /api/sandbox/attempts`, `POST /api/demo/clock {"reset": true}`, `make reset-db`.

## Deviations from the master prompt (and why)

- **HTTP framework: Starlette** (the framework FastAPI is built on) with a small typed routing layer
  (`app/web.py`) instead of FastAPI; **storage: stdlib `sqlite3`** instead of SQLAlchemy; **LLM calls: raw `httpx`**
  instead of the `openai` SDK; **scheduler: asyncio loop** instead of APScheduler. The build environment could not
  install FastAPI/SQLAlchemy/openai, and I wanted every endpoint exercised by real tests before handing it over.
  The API surface is identical: contract paths, shapes and error codes, plus `/openapi.json` and `/docs`
  generated from the same Pydantic models. Postgres is not supported (SQLite only).
- **`SUNWAI_PROJECT_SPEC.md` was not provided**, so prompts P1–P9 (`app/llm/prompts.py`), goals G1–G3
  (`app/tinyfish/goals.py`) and the 15 scenarios (`api/tests/scenarios/`) were written from the master prompt.
  Replace the prompt text if the spec differs; the code depends only on the output schemas.
- **Ombudsman opening date when the reply came after the 30-day wait**: the step opens at the end of the wait
  (the customer was already eligible then); the closing date uses the later of the two, as the scheme says.
- **Global events**: only `rule_changed` is pushed to case streams; rule-refresh progress is read with
  `GET /api/runs/{run_id}`.
- **Evidence pack PDF**: returns `400 BAD_REQUEST` ("use format=md") until implemented.

## Known limits

- Real portal field lists are not recorded yet (`data/portal_adapters/`), so live pre-fill matches fields by meaning.
- Consumer route waiting periods and the consumer-commission limitation are unverified and shown as
  `needs_verification` with no invented dates.
- Sector regulators for telecom / insurance are not covered (general consumer route plus a warning).
- The mock intake is keyword-based; live intake quality depends on the LLM and should be measured.
- No authentication (single demo user, as the contract specifies).

Sources used for verified facts are listed in [docs/VERIFIED.md](docs/VERIFIED.md).
