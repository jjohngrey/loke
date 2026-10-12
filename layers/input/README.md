# A: input and experience

Own `web/` (Next.js UI, HTTP proxy and input controls) and `desktop/` (Electron window).
Consume generated types from `@loke/contracts`. Do not grade answers or mutate learning state here.

- `npm run dev` starts the shared backend and web UI from the repository root.
- `npm run desktop` additionally opens Electron.
- `npm run typecheck` checks frontend boundaries.

Next work: active-quiz lifecycle, stronger recording cleanup, accessible activity controls, snooze/read notifications and visual refinement.
Provider keys stay in server environment variables. Electron renderer has no Node access.
