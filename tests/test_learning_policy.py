import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from loke_contracts.catalog import CARDS, CONCEPTS
from loke_contracts.models import EvidenceEvent, SourceChunk
from loke_intelligence.learning_demo import run_examples
from loke_intelligence.learning_models import (
    ActivityProgress,
    LearningContext,
    MisconceptionHypothesis,
    SemanticCandidate,
    SemanticInterpretation,
)
from loke_intelligence.learning_policy import choose_learning_activities, project_evidence
from loke_intelligence.policy import assess

TIME = datetime(2026, 10, 17, 1, tzinfo=UTC)


def answer(card_id="ap-depolarization", text="A", minute=0, assisted=False, event_id=None):
    card = next(c for c in CARDS if c["id"] == card_id)
    return EvidenceEvent(
        id=event_id or f"event:{card_id}:{minute}",
        concept_id=card["concept_id"],
        card_id=card_id,
        kind="quiz_answer",
        text=text,
        occurred_at=TIME + timedelta(minutes=minute),
        assessment=assess(card, text),
        assistance="after_explanation" if assisted else "none",
        source="quiz",
        grader="choice-rule-v1",
        expected_answer=card["answers"][0],
    )


def context(events=(), goal="action_potential_phases", **changes):
    return LearningContext(
        goal_concept_ids=[goal],
        concepts=deepcopy(CONCEPTS),
        items=deepcopy(CARDS),
        events=list(events),
        evaluated_at=TIME + timedelta(hours=1),
        **changes,
    )


def state(decision, concept="action_potential_phases"):
    return next(s for s in decision.evidence if s.concept_id == concept)


@pytest.mark.parametrize(
    "goal,first",
    [
        ("transmitter_release", "presynaptic_calcium_entry"),
        ("action_potential_phases", "resting_potential"),
        ("resting_potential", "ionic_gradients"),
        ("ionic_gradients", "ionic_gradients"),
    ],
)
def test_initial_choice_follows_goal_and_reviewed_graph(goal, first):
    decision = choose_learning_activities(context(goal=goal))
    assert decision.activities[0].concept_id == first
    assert len(decision.activities) <= 3
    assert all(s.status == "unchecked" for s in decision.evidence)


def test_wrong_answer_diagnostic_then_correct_prerequisite_changes_next_action():
    missed = answer()
    diagnostic = choose_learning_activities(context([missed])).activities[0]
    assert diagnostic.concept_id == "resting_potential"
    assert diagnostic.reason_code == "unchecked_prerequisite"
    assert diagnostic.reason_event_ids == [missed.id]
    assert diagnostic.prerequisite_path == ["action_potential_phases", "resting_potential"]
    assert diagnostic.support_text is None  # Independent diagnostic does not reveal its answer.
    checked = answer("resting-permeability", "K+", minute=1)
    next_action = choose_learning_activities(context([missed, checked])).activities[0]
    assert next_action.kind == "practice"
    assert next_action.concept_id == "action_potential_phases"
    assert next_action.teaching_mode == "explain_then_check"
    assert next_action.support_text


def test_assisted_retry_does_not_extend_deadline_and_independent_answer_advances():
    missed = answer()
    assisted = answer(text="B", minute=5, assisted=True)
    independent = answer(text="B", minute=10)
    decision = choose_learning_activities(context([missed, assisted]))
    assert state(decision).status == "assisted_correct"
    assert state(decision).next_review_at == TIME + timedelta(hours=24)
    assert decision.activities[0].reason_code == "assisted_retry"
    assert decision.activities[0].teaching_mode == "independent_recall"
    assert decision.activities[0].card.id == "ap-repolarization"
    advanced = choose_learning_activities(
        context([missed, assisted, independent], goal="transmitter_release")
    )
    assert state(advanced).status == "independent_correct"
    assert state(advanced).next_review_at == independent.occurred_at + timedelta(hours=72)
    assert advanced.activities[0].concept_id == "presynaptic_calcium_entry"


def test_success_on_another_item_does_not_erase_observed_miss():
    events = [
        answer(),
        answer("ap-repolarization", "A", minute=1),
        answer("resting-permeability", "K+", minute=2),
    ]
    decision = choose_learning_activities(context(events))
    assert state(decision).status == "conflicting"
    assert state(decision).next_review_at == TIME + timedelta(hours=24)
    assert decision.activities[0].reason_code == "conflicting_items"
    assert decision.activities[0].card.id == "ap-depolarization"
    assert decision.activities[0].teaching_mode == "guided_practice"


def test_ungraded_response_requires_clarification_without_scheduling_or_grading():
    event = answer(text="I am not sure")
    decision = choose_learning_activities(context([event]))
    assert state(decision).status == "uncertain"
    assert state(decision).evidence_ids == []
    assert state(decision).next_review_at is None
    assert decision.activities[0].kind == "clarify"
    assert decision.activities[0].reason_event_ids == [event.id]
    assert decision.activities[0].support_text is None


def test_reports_and_semantic_hypotheses_do_not_become_correctness():
    report = EvidenceEvent(
        id="report-1",
        concept_id="action_potential_phases",
        kind="study_report",
        text="Potassium entering causes depolarization.",
        occurred_at=TIME,
        assessment="not_assessed",
        assistance="none",
        source="text",
    )
    ctx = context([report])
    hypothesis = SemanticInterpretation(
        status="matched",
        concept_id="action_potential_phases",
        candidates=[SemanticCandidate(concept_id="action_potential_phases", relevance="strong")],
        hypotheses=[
            MisconceptionHypothesis(
                concept_id="action_potential_phases",
                description="Possible ion confusion",
                evidence_ids=[report.id],
            )
        ],
    )
    decision = choose_learning_activities(ctx, hypothesis)
    assert state(decision).status == "unchecked"
    assert state(decision).report_ids == [report.id]
    assert state(decision).evidence_ids == []
    assert decision.activities[0].reason_code == "reported_hypothesis"
    assert decision.activities[0].reason_event_ids == [report.id]
    assert "possible" in decision.activities[0].reason
    assert ctx.events == [report]


def test_source_supported_hypothesis_keeps_provenance_without_assessment():
    ctx = context(
        sources=[
            SourceChunk(
                source_id="note-1",
                title="Learner note",
                text="Potassium entering causes depolarization.",
            )
        ]
    )
    interpretation = SemanticInterpretation(
        status="matched",
        concept_id="action_potential_phases",
        candidates=[SemanticCandidate(concept_id="action_potential_phases", relevance="strong")],
        hypotheses=[
            MisconceptionHypothesis(
                concept_id="action_potential_phases",
                description="Possible confusion",
                source_ids=["note-1"],
            )
        ],
    )
    decision = choose_learning_activities(ctx, interpretation)
    assert decision.activities[0].reason_source_ids == ["note-1"]
    assert state(decision).status == "unchecked"
    interpretation.hypotheses[0].source_ids = ["invented"]
    with pytest.raises(ValueError, match="unavailable"):
        choose_learning_activities(ctx, interpretation)


def test_ambiguous_meaning_requests_clarification_without_guessing():
    interpretation = SemanticInterpretation(
        status="ambiguous",
        concept_id=None,
        candidates=[],
        clarification="Do you mean calcium entry or sodium entry?",
    )
    decision = choose_learning_activities(context(), interpretation)
    assert decision.status == "needs_clarification"
    assert decision.activities == []
    assert decision.clarification == interpretation.clarification


def test_due_review_precedes_new_learning_and_does_not_change_evidence():
    ctx = context([answer()], goal="transmitter_release")
    ctx.evaluated_at = TIME + timedelta(hours=24)
    before = ctx.model_dump()
    decision = choose_learning_activities(ctx)
    assert decision.activities[0].kind == "review"
    assert state(decision).review_due
    assert state(decision).status == "needs_practice"
    assert ctx.model_dump() == before


def test_graded_event_replay_order_is_deterministic():
    ctx = context([answer(), answer(text="B", minute=2)])
    expected = choose_learning_activities(ctx)
    ctx.events.reverse()
    assert choose_learning_activities(ctx) == expected


def test_progress_is_participation_not_mastery_and_suppresses_repeats():
    ctx = context(goal="resting_potential")
    seen = set()
    for _ in range(20):
        decision = choose_learning_activities(ctx)
        assert all(s.status == "unchecked" for s in decision.evidence)
        if not decision.activities:
            break
        for activity in decision.activities:
            assert activity.activity_id not in seen
            seen.add(activity.activity_id)
            ctx.progress.append(
                ActivityProgress(activity_id=activity.activity_id, status="completed")
            )
    else:
        pytest.fail("Plan cycles instead of exhausting the current activities")
    assert decision.status == "no_activity"
    assert ctx.events == []


def test_skip_chooses_another_card_and_activity_ids_survive_unchanged_context():
    ctx = context([answer()])
    first = choose_learning_activities(ctx).activities[0]
    assert choose_learning_activities(ctx).activities[0].activity_id == first.activity_id
    ctx.progress = [ActivityProgress(activity_id=first.activity_id, status="skipped")]
    next_action = choose_learning_activities(ctx).activities[0]
    assert next_action.concept_id == first.concept_id
    assert next_action.card.id != first.card.id
    assert next_action.activity_id != first.activity_id


@pytest.mark.parametrize("minutes", [1, 2, 3, 5, 10, 30])
def test_budget_and_public_cards(minutes):
    decision = choose_learning_activities(context(study_minutes=minutes))
    assert sum(a.minutes for a in decision.activities) <= minutes
    assert len(decision.activities) <= 3
    for activity in decision.activities:
        if activity.card:
            assert "answers" not in activity.card.model_dump()
    if minutes == 1:
        assert decision.status == "no_activity"


def test_depth_two_candidate_when_direct_prerequisite_was_only_assisted():
    ctx = context(
        [answer("calcium-trigger", "B"), answer(text="B", minute=1, assisted=True)],
        goal="transmitter_release",
    )
    decision = choose_learning_activities(ctx)
    resting = next(a for a in decision.activities if a.concept_id == "resting_potential")
    assert resting.prerequisite_path == [
        "presynaptic_calcium_entry",
        "action_potential_phases",
        "resting_potential",
    ]
    assert all(len(a.prerequisite_path) <= 3 for a in decision.activities)


@pytest.mark.parametrize(
    "damage",
    [
        "cycle",
        "unknown_goal",
        "unknown_edge",
        "mismatched_item",
        "duplicate_event",
        "report_grade",
        "forged_grade",
        "future_event",
    ],
)
def test_invalid_context_fails_closed(damage):
    ctx = context([answer()])
    if damage == "cycle":
        ctx.concepts[0].prerequisites = ["transmitter_release"]
    elif damage == "unknown_goal":
        ctx.goal_concept_ids = ["invented"]
    elif damage == "unknown_edge":
        ctx.concepts[0].prerequisites = ["invented"]
    elif damage == "mismatched_item":
        ctx.events[0].concept_id = "resting_potential"
    elif damage == "duplicate_event":
        ctx.events.append(ctx.events[0])
    elif damage == "report_grade":
        ctx.events[0].kind = "study_report"
    elif damage == "forged_grade":
        ctx.events[0].assessment = "correct"
    elif damage == "future_event":
        ctx.events[0].occurred_at = TIME + timedelta(days=10)
    with pytest.raises(ValueError):
        choose_learning_activities(ctx)


def test_naive_policy_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        LearningContext.model_validate(
            {**context().model_dump(), "evaluated_at": TIME.replace(tzinfo=None)}
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        choose_learning_activities(
            context().model_copy(update={"evaluated_at": TIME.replace(tzinfo=None)})
        )


def test_projection_is_narrow_item_evidence_not_mastery():
    states = project_evidence(context([answer(text="B")]))
    assert (
        next(s for s in states if s.concept_id == "action_potential_phases").status
        == "independent_correct"
    )
    assert next(s for s in states if s.concept_id == "resting_potential").status == "unchecked"


def test_review_uses_earliest_deadline_not_oldest_latest_observation():
    events = [
        answer(text="B"),
        answer("ap-repolarization", "A", minute=60),
        answer(text="B", minute=120, assisted=True),
    ]
    ctx = context(events)
    ctx.evaluated_at = TIME + timedelta(hours=26)
    review = choose_learning_activities(ctx).activities[0]
    assert review.kind == "review"
    assert review.card.id == "ap-depolarization"
    assert review.reason_event_ids == [events[-1].id]


def test_offline_examples_exercise_the_full_interpretation_to_policy_flow():
    examples = asyncio.run(run_examples())
    assert len(examples) == 9
    assert examples["reported-confusion"]["semantic"]["origin"] == "aliases"
    assert (
        examples["reported-confusion"]["decision"]["activities"][0]["reason_code"]
        == "reported_hypothesis"
    )
    assert (
        examples["wrong-answer"]["decision"]["activities"][0]["concept_id"] == "resting_potential"
    )
    assert (
        examples["prerequisite-checked"]["decision"]["activities"][0]["teaching_mode"]
        == "explain_then_check"
    )
    assert (
        examples["independent-progress"]["decision"]["activities"][0]["concept_id"]
        == "presynaptic_calcium_entry"
    )
    assert examples["ambiguous-input"]["decision"]["status"] == "needs_clarification"
