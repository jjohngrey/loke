# Learning-policy core, v1

This is B's standalone algorithm deliverable on `pauline/learning-policy`. It can be developed
and evaluated without A's UI or C's database. It is an explicit adaptive policy with optional
model-assisted interpretation, not a trained mastery/forgetting model.

The running HTTP application still uses `policy.py` and its existing contracts/fixtures.
The new core lives in `learning_models.py`, `learning_policy.py`, `semantics.py` and
`semantic_openrouter.py`. No application routes, shared generated contracts, storage schemas
or reviewed catalog entries are changed. Wiring the core into the coordinator is a later slice.

## Run the learning scenarios

```sh
.venv/bin/python -m loke_intelligence.learning_demo
.venv/bin/python -m loke_intelligence.learning_demo --scenario wrong-answer --json
.venv/bin/python -m pytest tests/test_learning_policy.py tests/test_semantics.py
```

The runner is read-only, uses fixed synthetic observations and the reviewed catalog, and makes
no paid calls. It shows a new goal, reported confusion, wrong answer, successful prerequisite,
assisted retry, independent progress, unclear answer, due review and ambiguous input.

## Algorithm boundary

`LearningContext` supplies resolved goal concept IDs, reviewed concepts/items, committed events,
completed/skipped activity IDs, available minutes and an explicit timezone-aware evaluation clock.
Optional source context is capped at two chunks. Model interpretation is separate from the event list.
Use the relevant committed history required to fold per-item evidence and deadline origins; a UI's
last-ten-events window is not sufficient to reconstruct lifetime learner state.

`choose_learning_activities(context, interpretation=None)` returns a `LearningDecision`: narrow
concept evidence, up to three budgeted activities, stable IDs, authored quiz cards without answer
keys, reason codes, real event references, prerequisite paths, teaching modes and reviewed resources.
It mutates neither context nor memory. Repeated evaluation of unchanged inputs returns the same IDs.

The policy validates unique/known IDs, authored item/concept associations, supported deterministic
grades, aware nonfuture observation times and an acyclic reviewed graph. Reports cannot carry
correctness. Existing `choice-rule-v1` grading is reused; model text cannot authorize a grade.

## Tracking and diagnosing

- Reports remain reports. No graded item means unchecked; an ungraded answer adds uncertainty.
- Evidence is folded by item, ordered by observation time then event ID. Correctness on a different
  item does not erase an unresolved wrong answer. Mixed latest item outcomes are conflicting.
- Assisted correct is distinct from independent correct. These labels describe recorded item
  outcomes, not validated understanding of an entire concept or numerical mastery probabilities.
- Incorrect or assisted evidence schedules +24h; independent correct schedules +72h. An assisted
  retry preserves an earlier deadline. The earliest outstanding per-item deadline drives review.
  Review reasons retain the observation establishing that deadline and any assisted retry.
- An ungraded answer does not update correctness or postpone review. A later graded answer resolves
  its clarification need. Actual assistance recording/reset remains a caller/session responsibility;
  this core never assumes that reloading a screen makes an answer independent.

Prerequisite diagnostics search nearest-first to depth two, using only supplied reviewed relations.
Paths are expressed dependent → prerequisite, e.g. action_potential_phases → resting_potential.
An independently correct prerequisite item stops further diagnostic traversal down that branch.
This is a bounded teaching heuristic, not a claim that all ancestor concepts are mastered.

## Next-action priority and teaching adaptation

1. Due review, ordered by deadline and catalog order.
2. Clarify an ungraded answer within the goal/selected-topic scope.
3. Check an unchecked prerequisite of an observed miss/conflict, nearest first.
4. Practice missed/conflicting items or independently recheck assisted correctness.
5. Diagnose a reported misconception hypothesis without declaring it a gap.
6. Check remaining depth-two goal prerequisites, then the goal item, then a reviewed explanation.

Ambiguous/unmatched semantic input returns an explicit clarification instead of guessing a topic.
The caller should retain its existing plan while resolving that input. Missed/conflicting evidence
is scoped to the goal and its prerequisite paths, plus a semantically selected topic. Due reviews
can concern any supplied concept. A goal already supported by independent item evidence does not
generate endless prerequisite checks, though future reviews remain eligible.

Independent diagnostics/reviews/retries reveal no answer explanation. After an observed miss,
practice includes the authored explanation; conflicting items select guided practice. An unclear
answer asks for clarification. If no authored item is available, goal explanation can use the
reviewed resource. Semantic hypotheses never add prerequisite edges or correctness evidence.

Completed/skipped IDs suppress the same activity within the caller's current session. An alternative
card can be offered; exhausted activities produce `no_activity`, not a fabricated three-step plan.
Progress records participation, not assessment. IDs change with the reason/evidence/card/goal path.
The caller must reset session progress intentionally for a later session; no persisted lifecycle
or active-quiz handling is introduced here. Budgets below an activity's duration produce no activity.

## Semantic interpretation and the model

`SemanticInterpreter` is an async port consuming `SemanticRequest`. Output is matched, ambiguous
or unmatched, with at most three known candidates and tentative misconception hypotheses.
It cannot contain grades, schedules, learner identity or graph edits.

The offline `AliasInterpreter` matches canonical IDs/labels/aliases on token boundaries, handles
explicit catalog plurals, and preserves tied meanings as ambiguous. A narrow demo cue detects a
possible potassium-entry/depolarization confusion; questions and negation do not assert that cue.
It is not general semantic reasoning. Broader paraphrases require model assistance or clarification.

Always call `interpret_safely(request, interpreter=None)`. With no adapter it stays local. An
explicit `OpenRouterSemanticInterpreter` provides one optional schema-constrained call using the
existing server environment configuration. Output and evidence/source IDs are validated against
the supplied context. Provider failures, malformed/unknown outputs and timeouts fall back locally;
unmatched fallback still asks for clarification. Cancellation propagates rather than producing a
late fallback result. No hidden retries or background model calls occur.

Model input is bounded to ten events, two chunks and a 12,000-character serialized-context budget;
oversized requests fall back rather than sending unbounded history. This is a character limit,
not a measured token budget. Timeout is at most 15 seconds and output at most 600 tokens. Strict
provider schemas require all properties; privacy/parameter routing follows the existing adapter.
Live provider compatibility/billing/retention are not verified by mocked tests.

## Later integration decisions

A will render the selected mode, question/support and reasons. C will provide reviewed context,
committed evidence and persisted session progress. B will adapt coordinator commits to this core.
Before enabling it in the application, agree goal resolution, typed reviewed/versioned graph input,
quiz lifecycle and assistance exposure/reset, clock separation, activity persistence and atomic
revision handling. The v1 core consumes these facts but does not implement their persistence.

Current assumptions to evaluate with the team: per-item conflict retention, a prerequisite's
independent item stopping deeper traversal, earliest outstanding item deadline, fixed catalog tie
order, and +24h/+72h review heuristics. These are explicit product rules to test, not research claims.
