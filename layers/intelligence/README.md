# B: intelligence

Own coordination, deterministic assessment/recommendations, topic proposals, audio normalization and scheduler eligibility.
`app.py` is the composition root; all other intelligence modules depend on the shared MemoryPort, never SQL implementation details.

- `policy.py`: curated card assessment and prerequisite/next-activity rules.
- `coordinator.py`: consent-aware learning turns, agent reuse, plans and reviews.
- `openrouter.py`: optional live typed proposal, with bounded timeout and provider restrictions.
- `audio.py`: direct OpenAI transcription; transcript is not committed until learner confirmation.
- `scheduler.py`: lifecycle for single-worker durable in-app reviews.

Default MODEL_MODE=demo makes no model API requests. MODEL_MODE=live needs an OpenRouter key; audio always needs a direct OpenAI key.
Next work: fully typed memory snapshots/commit outcomes, plan-completion semantics, ambiguity handling, active-quiz suppression, snooze, clock-safe revision checks and richer topic prompts.
