# VERIFIED.md — external facts the backend relies on

Every external fact used in code, with the date and how it was checked. Anything marked **TO VERIFY** must be
confirmed during the WP0 spike (`make spike`) before the demo, and this file updated.

## RBI Integrated Ombudsman Scheme 2026 (RB-IOS 2026)

| Fact | Value used | Source | Checked |
|---|---|---|---|
| Effective date | 2026-07-01 | RBI FAQ page (rbi.org.in, "Reserve Bank - Integrated Ombudsman Scheme, 2026"): "It comes into force with effect from July 1, 2026." | 2026-10-24, web fetch of https://www.rbi.org.in/commonperson/english/scripts/FAQs.aspx?Id=3407 |
| Must complain to the regulated entity first | yes | same page | 2026-10-24 |
| Wait before Ombudsman | 30 days without reply, or earlier if not satisfied with the reply | same page | 2026-10-24 |
| Filing window | 90 days from the later of (end of the 30-day timeline) and (date of the entity's last communication) | same page: "within 90 days from the date on which the above timeline expires or the date of the last communication from the concerned Regulated Entity, whichever is later" | 2026-10-24 |
| Complaints received before 1 July 2026 | stay under RB-IOS 2021 | same page | 2026-10-24 |
| Filing modes | https://cms.rbi.org.in, email crpc@rbi.org.in, post to CRPC Chandigarh; IVRS 14448 | same page | 2026-10-24 |
| 2021 scheme limits (1 year / 1 year + 30 days) | shown only as `superseded_value_note` | master prompt (verified by the team on 24 Oct 2026); not re-checked here | **TO VERIFY** on an official 2021 text if you show it on a slide |
| `cms.rbi.org.in` page text | not fetched | the web fetcher used here was refused by the site's robots rules; TinyFish Fetch/Agent may behave differently | **TO VERIFY** in WP0 |

The mock fixture `api/app/tinyfish/fixtures/fetch/rbi_scheme.json` holds these sentences as recorded on 2026-10-24.
Its note says the joins between quoted fragments may not match the page word for word: re-record the full page with
`make fixtures` (TinyFish Fetch, `ttl=0`) before relying on it. Live mode always fetches the page fresh.

## TinyFish APIs (docs.tinyfish.ai, read 2026-10-24)

| Item | Value used in code |
|---|---|
| Auth | header `X-API-Key` |
| Search | `GET https://api.search.tinyfish.ai?query&location&language` → `{query, results[{position, site_name, title, snippet, url, date?...}], total_results, page}`. `location` is a country code (docs list US, GB, FR, DE, BR, JP); **TO VERIFY** that `IN` is accepted. The client retries with `US` on HTTP 400. |
| Fetch | `POST https://api.fetch.tinyfish.ai` body `{urls[<=10], format: "markdown", ttl: 0}` → `{results[{url, final_url, title, description, language, text, ...}], errors[{url, error, status}]}`. The page content is in `text` (parser also accepts `markdown`/`content`). |
| Agent (stream) | `POST https://agent.tinyfish.ai/v1/automation/run-sse` with `url, goal, browser_profile, agent_config{mode, max_steps, max_duration_seconds}, capture_config{screenshots, recording, ...}, proxy_config{enabled, country_code}, output_schema` |
| SSE events | `STARTED`, `STREAMING_URL`, `PROGRESS{purpose}`, `TF_API_RESULT{tinyfish_api, result[]}`, `HEARTBEAT`, `COMPLETE{status, result, error?, help_url?, help_message?, profile_hint{message, setup_url, reason: auth_wall|bot_challenge}}` |
| Get run | `GET /v1/runs/{id}?screenshots=url` (status, result, steps[], video_url ~15 min expiry) |
| Cancel run | `POST /v1/runs/{id}/cancel` → `{run_id, status, cancelled_at, message}`; only for run-async / run-sse runs; idempotent |
| API error codes | `MISSING_API_KEY`, `INVALID_API_KEY` (401), `INSUFFICIENT_CREDITS`, `FREE_ALLOWANCE_EXHAUSTED` (402), `RATE_LIMIT_EXCEEDED` (429), `INTERNAL_ERROR` (500), `BACKEND_UNAVAILABLE` (502-504), `SERVICE_BUSY` (503). Run errors: `SERVICE_BUSY`, `TIMEOUT`, `BILLING_REJECTED`, `CONTENT_POLICY_VIOLATION`, `MAX_STEPS_EXCEEDED`, `SITE_BLOCKED`, `TASK_FAILED`, `CANCELLED`. |

Still **TO VERIFY** with real calls (`make spike`): latency, rate limits seen, whether `streaming_url` embeds in an
iframe, whether `output_schema` accepts the schemas in `app/tinyfish/goals.py` unchanged.

## Company grievance route (mock fixture)

| Company | Recorded | Source | Checked |
|---|---|---|---|
| PhonePe | grievance desk form `https://grievance.phonepe.com/`; levels: support (`https://support.phonepe.com/`), grievance desk, Nodal & Principal Nodal Officers (`https://grievance.phonepe.com/nodal-officer`). Emails are obfuscated on the page, so none recorded. | https://www.phonepe.com/grievance-policy/ | 2026-10-24, web fetch |

## Consumer (non-banking) route — all **TO VERIFY**

| Fact | Status in code |
|---|---|
| National Consumer Helpline `consumerhelpline.gov.in`, toll-free 1915 | shown as a forum; waiting period `null` → `needs_verification: true` |
| e-Jagriti `e-jagriti.gov.in` (successor of e-Daakhil) | shown as the last step, never automated |
| Consumer Protection Act 2019 limitation (believed 2 years) | not used for any date until fetched official text is verified |

## LLM model ids — **TO VERIFY**

`deepseek/deepseek-v4-flash`, `z-ai/glm-5.3-flash`, `nvidia/nemotron-3.5-lightning` are defaults from the setup guide.
The backend checks each id against the provider's `GET /models` at startup and reports `available` in `/api/health`.
Run `make spike` and write the confirmed ids here and in `.env`.

## Sandbox submit safety — not measured yet

Target: 0 submit clicks across ≥10 live runs on the public sandbox. Every live sandbox run appends a row to
`eval/live_runs.jsonl`; `make eval` turns it into the table in `eval/results.md`.
