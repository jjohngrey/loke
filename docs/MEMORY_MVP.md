# Local memory MVP

This slice connects the current chat UI to the existing PostgreSQL memory engine, adds usable
file and voice input, and makes retention permanent by default. It builds on the Layer C4 branch.
It does not claim completion of every future learning-policy feature in the weekend handoff.

## Acceptance

| Area | Delivered behavior |
| --- | --- |
| Consent | Explicit local storage consent and neural-signaling goal before content writes. |
| Chat | Backend-generated responses, atomic user/assistant ledger, stable chat scope, reload/restart history, 100-message pages and older-message loading. |
| Organization | Persisted folders, chat-to-folder assignment, title metadata, learner/generation-scoped reads. |
| Retention | Nullable learner deadline, no default expiry, migration of existing profile and retry-snapshot deadlines; explicit delete still cascades and rotates generation. |
| Attachments | TXT/Markdown/text-PDF extraction, 5 MB byte cap, 15,000-character draft cap, editable preview, explicit Send, source/report provenance without grading. |
| Voice | Microphone or audio upload, supported MIME selection, 30-second timer, 1 MB cap, local audio decoding/type/duration checks, OpenAI transcription, editable draft, explicit Send. |
| Voice output | Opt-in browser speech synthesis for committed replies. Browser/OS voice services may have their own network behavior. |
| Recovery | Frozen request IDs/payloads for uncertain retries; conflicts refresh without replay; drafts survive failed saves; stale reset responses ignored. |
| Lifecycle | Cancel processing/recording, release tracks/timers, discard late microphone grants and preprocessing responses on reset, consent changes or unmount. |
| Learning views | Current plan and diagnostic submission, recent evidence, recent source excerpts, durable in-app review reminders and reminder toggle. |
| Desktop | Exact local-origin media permission and navigation checks. |

## Deliberate limits

- Voice is clip-based transcription plus optional browser speech, not a continuous realtime or
  interruptible voice session. FFmpeg (ffmpeg and ffprobe) and OPENAI_API_KEY are required.
  No paid-provider or physical microphone calls are made by automated tests.
- Demo mode supports the reviewed neural-signaling curriculum. It is not a general-purpose LLM
  chat service. Live explanations remain opt-in through existing OpenRouter configuration.
- Original files and audio are not archived. PDF OCR, images, Office files and video are unsupported.
  This local PDF parser is not a hardened public upload sandbox.
- Source graph discovery/execution, explicit quiz start/cancel, plan activity completion and
  reminder snooze/read/dismiss remain extensions to the learning MVP. They are not prerequisites
  for saving and retrieving local memory. Existing diagnostics, reminder delivery and graph
  storage internals continue to work within their published contracts.
- The sidebar loads chats in pages of 100; search covers loaded titles and loaded message text.
  History pagination retrieves original records; model context remains bounded and summarized.
- Chat folder/title metadata supports 1000 customized chats and 200 folders. Unsaved drafts,
  selected chat, speech preferences and expansion state are temporary interface state.
- Retry caches retain their existing 24-hour/100-outcome bounds. This does not delete chat ledgers,
  sources or learning history. Permanent local storage is not an off-device backup.

## Verification

Run npm run check with LOKE_TEST_DATABASE_URL set to a separate PostgreSQL database, then
uv run ruff check . and npm run build. Tests create isolated random schemas, cover the retention
upgrade, cross-learner history isolation, pagination, restart, reset races, attachment validation,
unsaved previews, confirmed input provenance, and local audio decoding without a provider call.
