# Sunwai frontend

The Sunwai web interface helps a person understand a consumer complaint route, check the rule references behind its dates, prepare a complaint draft, and review a pre-filled form. The person submits on the official portal themselves.

## Start the frontend

```bash
cd web
pnpm install
Copy-Item .env.example .env.local   # PowerShell; use cp on macOS/Linux
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). The default `NEXT_PUBLIC_API_MODE=mock` works without a backend. It stores demo cases and demo controls in this browser only. Use `NEXT_PUBLIC_API_MODE=live` with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` to connect to the API described in `API_CONTRACT.md`.

## Frontend routes

- `/` complaint intake, scenarios, optional voice input and image attachments
- `/case/[id]` facts, complaint ladder, proof stamps, editable draft, agent approval, review packet and timeline
- `/case/[id]/pack` print-friendly evidence pack
- `/cases` case list
- `/sandbox/grievance` fictional Kanakpur Demo Bank form used for rehearsals
- `/sandbox/status` deterministic demo status lookup
- `/about` how the flow and handoff work

The floating Demo controls (or `Shift+D`) set the simulated date, rehearse a successful run / OTP handoff / failure, and show sandbox review and submit-click counts. Use the case workspace’s Plan, Draft, Agent and Timeline tabs on mobile.

## Configuration

Only public browser configuration belongs in `.env.local`:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_API_MODE=mock|live`
- `NEXT_PUBLIC_SANDBOX_PUBLIC_URL`

No LLM or browser-agent credentials belong in the frontend. The API client validates case, summary and clock responses against the contract-shaped Zod schemas before rendering live data.

## Design notes

See [`DESIGN.md`](./DESIGN.md) for tokens, interaction patterns, accessibility choices and the scope of the demo visuals.
