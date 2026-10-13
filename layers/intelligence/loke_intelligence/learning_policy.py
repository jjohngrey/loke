"""Pure adaptive policy: observed item evidence + reviewed graph -> traceable activities.

No database, HTTP calls, wall clock, learner mutation or model-authorized grades.
The legacy policy.py remains the running application's planner until integration.
"""

import hashlib
import json
from collections import deque
from datetime import timedelta

from loke_contracts.models import QuizCard

from .learning_models import (
    ConceptEvidence,
    LearningActivity,
    LearningContext,
    LearningDecision,
    SemanticInterpretation,
    SemanticRequest,
)
from .policy import assess
from .semantics import validate_interpretation


def validate_context(context: LearningContext) -> None:
    if context.evaluated_at.utcoffset() is None:
        raise ValueError("Policy evaluation requires a timezone-aware clock.")
    concepts = {c.id: c for c in context.concepts}
    items = {item.id: item for item in context.items}
    if len(concepts) != len(context.concepts) or len(items) != len(context.items):
        raise ValueError("Concept and item IDs must be unique.")
    if len(set(context.goal_concept_ids)) != len(context.goal_concept_ids):
        raise ValueError("Goal concepts must be unique.")
    if not set(context.goal_concept_ids) <= concepts.keys():
        raise ValueError("Goal references an unknown concept.")
    if any(item.concept_id not in concepts for item in context.items):
        raise ValueError("Item references an unknown concept.")
    visiting, visited = set(), set()

    def visit(cid):
        if cid not in concepts:
            raise ValueError("Graph references an unknown prerequisite.")
        if cid in visiting:
            raise ValueError("Reviewed prerequisites must be acyclic.")
        if cid in visited:
            return
        visiting.add(cid)
        for parent in concepts[cid].prerequisites:
            visit(parent)
        visiting.remove(cid)
        visited.add(cid)

    for cid in concepts:
        visit(cid)
    if len({e.id for e in context.events}) != len(context.events):
        raise ValueError("Evidence IDs must be unique; deduplicate at the commit boundary.")
    for event in context.events:
        if event.occurred_at.utcoffset() is None or event.occurred_at > context.evaluated_at:
            raise ValueError(
                "Evidence needs an aware observation timestamp no later than evaluation."
            )
        if event.concept_id is not None and event.concept_id not in concepts:
            raise ValueError("Evidence references an unknown concept.")
        if event.kind == "study_report":
            if event.assessment != "not_assessed":
                raise ValueError("A study report cannot be correctness evidence.")
            continue
        if (
            event.card_id not in items
            or event.source != "quiz"
            or event.concept_id != items[event.card_id].concept_id
        ):
            raise ValueError("Quiz evidence must reference its authored item and concept.")
        if event.grader != "choice-rule-v1" or event.assessment != assess(
            items[event.card_id].model_dump(), event.text
        ):
            raise ValueError("Quiz assessment must agree with the supported deterministic grader.")


def _project(context: LearningContext) -> dict[str, ConceptEvidence]:
    result = {}
    ordered = sorted(context.events, key=lambda e: (e.occurred_at, e.id))
    for concept in context.concepts:
        events = [e for e in ordered if e.concept_id == concept.id]
        quizzes = [e for e in events if e.kind == "quiz_answer"]
        graded = [e for e in quizzes if e.assessment in {"correct", "incorrect"}]
        latest_by_card, due_by_card, review_reasons = {}, {}, {}
        for event in graded:
            latest_by_card[event.card_id] = event
            due = event.occurred_at + timedelta(
                hours=72 if event.assessment == "correct" and event.assistance == "none" else 24
            )
            if event.assessment == "correct" and event.assistance != "none":
                prior = due_by_card.get(event.card_id)
                review_reasons[event.card_id] = list(
                    dict.fromkeys(
                        [
                            *(
                                review_reasons.get(event.card_id, [])
                                if prior is not None and prior <= due
                                else []
                            ),
                            event.id,
                        ]
                    )
                )
                due = min(due, prior) if prior is not None else due
            else:
                review_reasons[event.card_id] = [event.id]
            due_by_card[event.card_id] = due
        latest = list(latest_by_card.values())
        wrong = any(e.assessment == "incorrect" for e in latest)
        independent = any(e.assessment == "correct" and e.assistance == "none" for e in latest)
        assisted = any(e.assessment == "correct" and e.assistance != "none" for e in latest)
        pending = quizzes[-1] if quizzes and quizzes[-1].assessment == "ungraded" else None
        status = "unchecked"
        if wrong:
            status = "conflicting" if independent else "needs_practice"
        elif assisted:
            status = "assisted_correct"
        elif independent:
            status = "independent_correct"
        elif pending:
            status = "uncertain"
        review_card = (
            min(due_by_card, key=lambda cid: (due_by_card[cid], cid)) if due_by_card else None
        )
        due = due_by_card[review_card] if review_card else None
        result[concept.id] = ConceptEvidence(
            concept_id=concept.id,
            status=status,
            evidence_ids=[e.id for e in latest],
            report_ids=[e.id for e in events if e.kind == "study_report"],
            latest_event_id=quizzes[-1].id if quizzes else None,
            pending_answer_id=pending.id if pending else None,
            next_review_at=due,
            review_due=due is not None and due <= context.evaluated_at,
            review_card_id=review_card,
            review_reason_event_ids=review_reasons[review_card] if review_card else [],
        )
    return result


def project_evidence(context: LearningContext) -> list[ConceptEvidence]:
    validate_context(context)
    return list(_project(context).values())


def choose_learning_activities(
    context: LearningContext, interpretation: SemanticInterpretation | None = None
) -> LearningDecision:
    validate_context(context)
    states = _project(context)
    concepts = {c.id: c for c in context.concepts}
    events = {e.id: e for e in context.events}
    if interpretation is not None:
        # Semantic citations are validated against context, but never become graded evidence.
        request = SemanticRequest(
            text="policy interpretation validation",
            concepts=context.concepts,
            events=context.events[-10:],
            sources=context.sources,
        )
        validate_interpretation(interpretation, request)
        if interpretation.status != "matched":
            return LearningDecision(
                status="needs_clarification",
                evidence=list(states.values()),
                activities=[],
                clarification=interpretation.clarification or "Which concept should we focus on?",
            )
    unavailable = {p.activity_id for p in context.progress}
    candidates = []

    def add(
        priority,
        kind,
        cid,
        code,
        reason,
        ids,
        mode,
        path=None,
        preferred_card=None,
        source_ids=None,
    ):
        pool = [item for item in context.items if item.concept_id == cid]
        # Retry observed misses first; otherwise prefer an item without a graded answer.
        graded_cards = {
            e.card_id for e in context.events if e.assessment in {"correct", "incorrect"}
        }
        pool.sort(key=lambda item: (item.id != preferred_card, item.id in graded_cards))
        if kind == "learn":
            pool = [None]
        for item in pool:
            identity = dict(
                kind=kind,
                concept=cid,
                card=item.id if item else None,
                reason=code,
                evidence=sorted(ids),
                sources=sorted(source_ids or []),
                path=path or [],
                goals=sorted(context.goal_concept_ids),
            )
            activity_id = (
                "activity:"
                + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
            )
            if activity_id in unavailable:
                continue
            public_card = (
                QuizCard.model_validate(
                    {
                        key: getattr(item, key)
                        for key in ("id", "concept_id", "kind", "prompt", "options")
                    }
                )
                if item
                else None
            )
            candidates.append(
                (
                    priority,
                    LearningActivity(
                        activity_id=activity_id,
                        kind=kind,
                        concept_id=cid,
                        card=public_card,
                        minutes=3 if kind == "learn" else 2,
                        reason_code=code,
                        reason=reason,
                        reason_event_ids=ids,
                        reason_source_ids=source_ids or [],
                        prerequisite_path=path or [],
                        teaching_mode=mode,
                        support_text=item.explanation
                        if item and mode in {"explain_then_check", "guided_practice"}
                        else None,
                        resource_url=concepts[cid].resource_url,
                    ),
                )
            )
            return

    def ancestors(cid, max_depth):
        queue = deque([(cid, [])])
        seen = {cid}
        while queue:
            current, path = queue.popleft()
            if max_depth is not None and len(path) >= max_depth:
                continue
            for parent in concepts[current].prerequisites:
                if parent in seen:
                    continue
                seen.add(parent)
                next_path = [*path, current]  # dependent -> ... -> prerequisite, explicitly below
                yield parent, [*next_path, parent]
                if states[parent].status != "independent_correct":
                    queue.append((parent, next_path))

    relevant = set(context.goal_concept_ids)
    for goal in context.goal_concept_ids:
        relevant.update(cid for cid, _ in ancestors(goal, None))
    if interpretation and interpretation.concept_id:
        relevant.add(interpretation.concept_id)

    for order, (cid, state) in enumerate(states.items()):
        if state.review_due:
            add(
                (0, state.next_review_at, order),
                "review",
                cid,
                "review_due",
                "Scheduled practice is due; this does not mean forgetting was measured.",
                state.review_reason_event_ids,
                "independent_recall",
                preferred_card=state.review_card_id,
            )
        if cid not in relevant:
            continue
        if state.pending_answer_id:
            add(
                (1, order),
                "clarify",
                cid,
                "ungraded_answer",
                "The last answer could not be graded. Clarify it before drawing a conclusion.",
                [state.pending_answer_id],
                "clarify_response",
                preferred_card=events[state.pending_answer_id].card_id,
            )
            continue
        if state.status in {"needs_practice", "conflicting"}:
            for parent, path in ancestors(cid, 2):
                if states[parent].status == "unchecked":
                    add(
                        (2, len(path), order),
                        "diagnostic",
                        parent,
                        "unchecked_prerequisite",
                        f"{concepts[parent].label} supports {concepts[cid].label}; it has not been checked yet.",
                        state.evidence_ids,
                        "independent_recall",
                        path,
                    )
            wrong = [events[e] for e in state.evidence_ids if events[e].assessment == "incorrect"]
            add(
                (3, order),
                "practice",
                cid,
                "conflicting_items" if state.status == "conflicting" else "incorrect_item",
                "Recorded items disagree; revisit the missed item."
                if state.status == "conflicting"
                else "A recorded answer needs practice; use the reviewed explanation and check again.",
                state.evidence_ids,
                "guided_practice" if state.status == "conflicting" else "explain_then_check",
                preferred_card=wrong[-1].card_id,
            )
        elif state.status == "assisted_correct":
            add(
                (3, order),
                "practice",
                cid,
                "assisted_retry",
                "The correct answer followed help. Try an independent check before moving on.",
                state.evidence_ids,
                "independent_recall",
            )

    if interpretation:
        for order, hypothesis in enumerate(interpretation.hypotheses):
            cid = hypothesis.concept_id
            if states[cid].status == "unchecked":
                add(
                    (4, order),
                    "diagnostic",
                    cid,
                    "reported_hypothesis",
                    "The report suggests a possible confusion. Check it; this is not an established gap.",
                    hypothesis.evidence_ids,
                    "independent_recall",
                    source_ids=hypothesis.source_ids,
                )

    for order, goal in enumerate(context.goal_concept_ids):
        if states[goal].status != "unchecked":
            continue
        for parent, path in ancestors(goal, 2):
            if states[parent].status == "unchecked":
                add(
                    (5, len(path), order),
                    "diagnostic",
                    parent,
                    "goal_prerequisite",
                    f"Check {concepts[parent].label}, a prerequisite on the path to your goal.",
                    [],
                    "independent_recall",
                    path,
                )
        add(
            (6, order),
            "diagnostic",
            goal,
            "goal_check",
            "Check the goal concept with an authored item before assuming understanding.",
            [],
            "independent_recall",
        )
        add(
            (7, order),
            "learn",
            goal,
            "goal_explanation",
            "Use the reviewed resource to connect the concept to your goal; reading is not correctness evidence.",
            [],
            "explanation",
        )

    # One action per concept, at most three actions, and never exceed the remaining budget.
    selected, seen, remaining = [], set(), context.study_minutes
    for _, activity in sorted(candidates, key=lambda pair: pair[0]):
        if activity.concept_id in seen or activity.minutes > remaining:
            continue
        selected.append(activity)
        seen.add(activity.concept_id)
        remaining -= activity.minutes
        if len(selected) == 3:
            break
    return LearningDecision(
        status="ready" if selected else "no_activity",
        evidence=list(states.values()),
        activities=selected,
    )
