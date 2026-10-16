import hashlib
import os
from datetime import datetime, timedelta
from uuid import uuid4

from loke_contracts.catalog import CARDS, CONCEPTS
from loke_contracts.models import (
    AnswerInput,
    ContextBundle,
    EvidenceEvent,
    GoalInput,
    LearningInput,
    LearningView,
    QuizCard,
)
from loke_contracts.ports import MemoryPort

from . import policy
from .openrouter import propose


def fingerprint(payload) -> str:
    return hashlib.sha256(payload.model_dump_json().encode()).hexdigest()


class Coordinator:
    def __init__(self, memory: MemoryPort, mode: str = "demo"):
        self.memory = memory
        self.mode = mode

    def _view(self, learner_id: str, snapshot: dict) -> LearningView:
        card_id = snapshot.get("active_card_id")
        card = next((c for c in CARDS if c["id"] == card_id), None)
        public_card = (
            QuizCard(**{k: card[k] for k in ["id", "concept_id", "kind", "prompt", "options"]})
            if card
            else None
        )
        return LearningView(
            learner_id=learner_id,
            generation_id=snapshot["generation_id"],
            graph_version=snapshot.get("graph_version"),
            goal=snapshot["goal"],
            storage_consent=snapshot["storage_consent"],
            reminders_enabled=snapshot["reminders_enabled"],
            agent_id=snapshot["agent_id"],
            state_revision=snapshot["state_revision"],
            plan_revision=snapshot["plan_revision"],
            model_mode=self.mode,
            demo_clock_hours=snapshot["demo_clock_hours"],
            response=snapshot["response"],
            plan=snapshot["plan"],
            active_quiz=public_card,
            states=list(snapshot["states"].values()),
            concepts=CONCEPTS,
            events=[EvidenceEvent(**e) for e in snapshot["events"][-10:]],
            notifications=[
                {k: n[k] for k in ("id", "title", "reason_event_id", "created_at")}
                for n in snapshot["notifications"]
            ],
            sources=snapshot["sources"][-2:],
        )

    def view(self, learner_id: str) -> LearningView:
        return self._view(learner_id, self.memory.snapshot(learner_id))

    def _replan(self, snapshot: dict):
        snapshot["plan"] = policy.choose_plan(snapshot)
        snapshot["plan_revision"] += 1
        if snapshot["plan"]:
            card = policy.card_for(snapshot["plan"][0]["concept_id"], snapshot["events"])
            snapshot["active_card_id"] = card["id"]

    def goal(self, learner_id: str, payload: GoalInput) -> LearningView:
        if not payload.storage_consent:
            raise ValueError("Consent is required to save your learning history.")
        if not any(
            term in payload.goal.lower()
            for term in ["neuro", "neuron", "synap", "action potential", "signaling", "membrane"]
        ):
            raise ValueError("This scaffold supports neural signaling. Choose a neuroscience goal.")

        def transform(s):
            s.update(
                goal=payload.goal,
                storage_consent=True,
                reminders_enabled=payload.reminders_enabled,
                study_minutes=payload.study_minutes,
            )
            s["agent_id"] = s["agent_id"] or str(uuid4())
            s["response"] = (
                "Your goal is saved. Start with one short check, then connect it to transmitter release."
            )
            self._replan(s)

        return self._view(
            learner_id,
            self.memory.mutate(
                learner_id, payload.request_id, fingerprint(payload), None, transform
            ),
        )

    async def input(self, learner_id: str, payload: LearningInput) -> LearningView:
        snapshot = self.memory.snapshot(learner_id)
        if not snapshot["storage_consent"]:
            raise ValueError("Save a goal and consent before submitting study material.")
        concept_id = policy.match_concept(payload.text)
        explanation = "Saved as learner-reported activity. A short recall question will give us stronger evidence."
        if self.mode == "live":
            context = ContextBundle(
                learner_id=learner_id,
                agent_id=snapshot["agent_id"],
                goal=snapshot["goal"],
                state_revision=snapshot["state_revision"],
                plan_revision=snapshot["plan_revision"],
                concepts=CONCEPTS,
                states=list(snapshot["states"].values()),
                events=snapshot["events"][-10:],
                sources=self.memory.retrieve_sources(learner_id, payload.text),
            )
            proposal = await propose(payload.text, context)
            concept_id, explanation = proposal.concept_id, proposal.explanation

        def transform(s):
            if s["agent_id"] != snapshot["agent_id"] or not s["storage_consent"]:
                raise ValueError("Learning history was reset. Submit again after consenting.")
            s["events"].append(
                dict(
                    id=str(uuid4()),
                    concept_id=concept_id,
                    card_id=None,
                    kind="study_report",
                    text=payload.text,
                    occurred_at=policy.now(s).isoformat(),
                    assessment="not_assessed",
                    assistance="none",
                    source=payload.mode,
                )
            )
            if payload.mode == "attachment":
                source_id = hashlib.sha256(payload.text.encode()).hexdigest()[:16]
                chunks = [payload.text[i : i + 1200] for i in range(0, len(payload.text), 1200)]
                s["sources"] = [c for c in s["sources"] if not c["source_id"].startswith(source_id)]
                s["sources"].extend(
                    dict(source_id=f"{source_id}:{i}", title="Your study note", text=chunk)
                    for i, chunk in enumerate(chunks)
                )
            s["response"] = explanation
            if concept_id:
                s["active_card_id"] = policy.card_for(concept_id, s["events"])["id"]

        return self._view(
            learner_id,
            self.memory.mutate(
                learner_id,
                payload.request_id,
                fingerprint(payload),
                snapshot["state_revision"],
                transform,
            ),
        )

    def answer(self, learner_id: str, payload: AnswerInput) -> LearningView:
        def transform(s):
            if not s["storage_consent"]:
                raise ValueError("Save a goal before answering.")
            if payload.card_id != s["active_card_id"]:
                raise ValueError("That question is no longer active. Refresh before answering.")
            card = next(c for c in CARDS if c["id"] == payload.card_id)
            assessment = policy.assess(card, payload.answer)
            concept_id = card["concept_id"]
            assisted = concept_id in s["assisted_concepts"]
            event = dict(
                id=str(uuid4()),
                concept_id=concept_id,
                card_id=card["id"],
                kind="quiz_answer",
                text=payload.answer,
                occurred_at=policy.now(s).isoformat(),
                assessment=assessment,
                expected_answer=card["answers"][0],
                grader="choice-rule-v1",
                assistance="after_explanation" if assisted else "none",
                source="quiz",
            )
            s["events"].append(event)
            if assessment == "ungraded":
                s["response"] = (
                    "I could not grade that response. Use one of the displayed options or a short ion name."
                )
                return
            old_state = s["states"].get(concept_id, {})
            due = (
                policy.now(s)
                + timedelta(hours=72 if assessment == "correct" and not assisted else 24)
            ).isoformat()
            if assessment == "correct" and assisted and old_state.get("next_review_at"):
                due = old_state["next_review_at"]
            s["states"][concept_id] = dict(
                concept_id=concept_id,
                status="recent_unassisted_correct"
                if assessment == "correct" and not assisted
                else "needs_practice",
                evidence_ids=[event["id"]],
                next_review_at=due,
            )
            s["review_jobs"] = [j for j in s["review_jobs"] if j["concept_id"] != concept_id]
            s["review_jobs"].append(
                dict(
                    id=f"review:{event['id']}",
                    kind="review",
                    concept_id=concept_id,
                    reason_event_id=event["id"],
                    due_at=due,
                    status="pending",
                )
            )
            if concept_id not in s["assisted_concepts"]:
                s["assisted_concepts"].append(concept_id)
            label = (
                "Correct on this item."
                if assessment == "correct"
                else "This item needs another check."
            )
            s["response"] = f"{label} {card['explanation']}"
            self._replan(s)

        return self._view(
            learner_id,
            self.memory.mutate(
                learner_id, payload.request_id, fingerprint(payload), None, transform
            ),
        )

    def reminders(self, learner_id: str, enabled: bool) -> LearningView:
        def transform(s):
            if not s["storage_consent"]:
                raise ValueError("Save a goal before enabling reminders.")
            s["reminders_enabled"] = enabled

        result = self.memory.mutate(learner_id, str(uuid4()), str(enabled), None, transform)
        return self._view(learner_id, result)

    def advance_clock(self, learner_id: str, hours: int) -> LearningView:
        if os.getenv("DEMO_CLOCK_ENABLED", "false").lower() != "true":
            raise ValueError("Demo clock is disabled.")

        def transform(s):
            if not s["storage_consent"]:
                raise ValueError("Save a goal before advancing the demo clock.")
            s["demo_clock_hours"] += hours

        self.memory.mutate(learner_id, str(uuid4()), str(hours), None, transform)
        self.tick(learner_id)
        return self.view(learner_id)

    def tick(self, learner_id: str):
        snapshot = self.memory.snapshot(learner_id)
        if not snapshot["storage_consent"] or not snapshot["reminders_enabled"]:
            return
        due = [
            j
            for j in snapshot["review_jobs"]
            if j["status"] == "pending"
            and datetime.fromisoformat(j["due_at"]) <= policy.now(snapshot)
        ]
        if not due:
            return
        last = snapshot["notifications"][-1] if snapshot["notifications"] else None
        if last and policy.now(snapshot) - datetime.fromisoformat(last["created_at"]) < timedelta(
            hours=24
        ):
            return
        job = due[0]

        def transform(s):
            current = next((j for j in s["review_jobs"] if j["id"] == job["id"]), None)
            if not current or current["status"] != "pending":
                return
            current["status"] = "notified"
            label = next(c["label"] for c in CONCEPTS if c["id"] == job["concept_id"])
            s["notifications"].append(
                dict(
                    id=f"notification:{job['id']}",
                    kind="notification",
                    title=f"Review due: {label}",
                    reason_event_id=job["reason_event_id"],
                    created_at=policy.now(s).isoformat(),
                )
            )
            self._replan(s)

        self.memory.mutate(
            learner_id, f"dispatch:{job['id']}", job["id"], snapshot["state_revision"], transform
        )

    def expire(self):
        self.memory.expire()
