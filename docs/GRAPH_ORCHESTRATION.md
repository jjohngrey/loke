# Standalone hybrid graph orchestration

The orchestrator selects existing source graphs, chooses direct execution or bounded delegation,
and merges cited recommendations into one study plan. It reuses source validation and the learning
policy. HTTP routes, generated application contracts, database schemas and the neuroscience UI
are unchanged. OpenPoke's delegation threshold was not verified; these are Loke's own rules.

## Try the offline scenarios

```sh
.venv/bin/python -m loke_intelligence.orchestration_demo
.venv/bin/python -m loke_intelligence.orchestration_demo --scenario repeated --json
.venv/bin/python -m pytest -q tests/test_orchestrator.py
```

The six synthetic scenarios cover direct execution, scripted model-selected delegation, scripted
physics classification, ambiguous sources, multi-graph synthesis and caller-managed memory across
turns. The fixture definitions illustrate routing and provenance, not scientific teaching quality.
Scripted routing uses the model interface without making a provider call.

`--live` explicitly sends synthetic graph summaries and the request to OpenRouter using
`OPENROUTER_API_KEY`, `TEXT_MODEL` and `OPENROUTER_PROVIDER`. It is billable. Default execution
does not load credentials or call a provider. No live calls were used for verification.

## Python boundary

Use `GraphOrchestrator.run(OrchestrationInput(...))`. All standalone contracts are in
`orchestration_models.py`; no shared HTTP contract export is required.

- `GraphRegistration` associates an opaque, stable `graph_id` with a `SourceDocument`, its
  `SourceGraph`, authored assessment items, committed evidence and session activity progress.
- `OrchestrationInput` contains learner scope, request text, registrations, prior specialist
  snapshots, study minutes, an aware evaluation clock and `allow_inferred` (default true).
  Optional `confirmed_targets` selects graph/concept IDs after clarification and bypasses the model.
- `RoutingModel.route(RoutingRequest)` returns a strict `RoutingProposal`: direct/delegate/clarify,
  graph-specific goal targets, provisional subject assignments and an optional clarification.
  Model context contains concepts, citation quotes, existing goal IDs and current-version inferred
  subject metadata. It excludes learner identity, assessment items, history and complete documents.
- `GraphWorkerPort.run(WorkerTask)` returns a task/version-bound `WorkerResult`. Production workers
  use the existing source planner; the interface permits failure/concurrency testing. A returned
  decision must equal the authoritative source-policy decision before it can update memory.
- `OrchestrationResult` contains status, routing mode/origin, namespaced activities retaining
  original policy IDs, successful worker decisions, snapshots, safe warnings and clarification.
  Callers should display `activities` as the unified plan; worker plans are per-graph diagnostics.

For example, given a registration named `physics`:

```python
request = OrchestrationInput(
    learner_scope="learner-a",
    text="Acceleration",
    graphs=[physics],
    evaluated_at=aware_clock,
    study_minutes=10,
)
result = await GraphOrchestrator().run(request)
next_request = request.model_copy(update={"snapshots": result.snapshots})
next_result = await GraphOrchestrator().run(next_request)
```

Supply authoritative evidence and completed/skipped progress each turn. Snapshots retain references
to these records, not their contents or progress statuses. Passing snapshots alone does not mark
activities completed or reconstruct omitted learner history. Scope/access checks on registered
documents and evidence remain the caller's responsibility; the core has no authentication store.

## Routing and execution rules

Local routing matches concept labels and aliases on token boundaries, including punctuation and
case normalization. One clear graph runs directly; distinct, explicit multi-graph matches delegate.
Shared concept matches clarify rather than choosing the first source. Subject-only requests need
the optional model unless they literally match a known concept. There is no hardcoded subject list.

The optional `OpenRouterRoutingModel` classifies subjects and chooses delegation in one strict
response. Labels and aliases remain inferred; every subject cites exact supplied document text.
Citation validation establishes provenance, not semantic correctness of the subject classification.
Duplicate subject/concept matches require clarification. New model-only paraphrase goal mappings
need confirmation; the model can select existing, already resolved graph goals for a subject request.

The routing call has a 15-second timeout, 12,000 serialized input-character limit and 1,200 output
tokens, with no retries. Oversized context is not silently truncated: it uses conservative local
routing. Invalid proposals, unknown IDs and provider failures also fall back locally. Unresolved
graph coverage must be clarified before any worker runs.

At most three graphs are selected, with one task per graph and at most three goals per task.
Larger requests ask for narrowing. Direct mode executes selected tasks serially; delegated mode
schedules up to three concurrently. Both use the same worker with a five-second timeout. Workers
have no provider, persistence or recursive spawning capabilities. The built-in CPU worker runs
off the event loop; cancelling its await cannot kill a running Python thread, but that pure thread
cannot commit state or produce a late snapshot update. This is not a process sandbox.

Graph fingerprints, document versions, unique IDs, all edge references and exact citations are
validated. Existing depth-two prerequisite diagnostics, held-edge exclusion, inferred-edge
labeling, authored grading and no-question reading fallback are preserved. Set `allow_inferred=False`
to exclude inferred prerequisites. Workers do not discover sources, generate quizzes or create
cross-document edges.

Synthesis considers only each graph's next activity, preserving each worker's ordering. It selects
heads by the existing policy reason priorities, then graph ID. Inferred prerequisites retain their
miss-driven or goal-driven priority. The merged plan contains at most three activities and never
exceeds the one shared budget. If a head will not fit, that graph stops contributing, so a later
dependent cannot jump ahead of the omitted prerequisite. The merge does not introduce fairness
quotas or combine assessment states across sources.

## Structured specialist memory and failures

Specialist IDs derive from `(learner_scope, graph_id)`. Two physics documents remain separate
specialists; subject renaming does not change identity. A caller must keep graph IDs stable across
document replacement if it wants to retain specialist identity.

Successful validated work returns updated snapshots containing the current graph hash, inferred
subject metadata, visited/recommended concept references, usable prerequisite edges, citations and
consumed evidence/progress references. These findings describe planning work, not completed study
or learner mastery. No generated summary, grade, new evidence or database write is performed.

On unchanged graphs, valid existing graph references accumulate with new findings. A changed graph
hash discards cached traversal/findings and subject tags; current evidence/progress must validate
against the replacement graph. Old concept IDs are never migrated by matching labels. Caller-owned
input objects are copied, and snapshots for unselected graphs are retained.

Clarification returns prior snapshots unchanged. A failed or invalid worker retains its prior
snapshot; other successful workers return a `partial` result and can update their own snapshots.
All failed tasks yield `failed` with no activities; successful but exhausted/under-budget plans
yield `no_activity`. Bad caller identities or duplicate registrations raise `ValueError`. Provider
and worker exceptions produce safe warnings without exposing exception text. Cancellation propagates
instead of producing fallback or a late result. The caller decides when to persist returned snapshots.

Durable storage, HTTP/UI integration and autonomous model/tool-loop specialists remain later work.
