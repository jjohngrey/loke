"""Offline, read-only scenario runner: python -m loke_intelligence.learning_demo."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from loke_contracts.catalog import CARDS, CONCEPTS
from loke_contracts.models import EvidenceEvent

from .learning_models import LearningContext, SemanticRequest
from .learning_policy import choose_learning_activities
from .policy import assess
from .semantics import interpret_safely

START = datetime(2026, 10, 17, 1, tzinfo=UTC)


def observed_answer(card_id, text, minute=0, assisted=False):
    item = next(item for item in CARDS if item["id"] == card_id)
    return EvidenceEvent(
        id=f"example:{card_id}:{minute}",
        concept_id=item["concept_id"],
        card_id=card_id,
        kind="quiz_answer",
        text=text,
        occurred_at=START + timedelta(minutes=minute),
        assessment=assess(item, text),
        assistance="after_explanation" if assisted else "none",
        source="quiz",
        grader="choice-rule-v1",
        expected_answer=item["answers"][0],
    )


async def run_examples() -> dict:
    miss = observed_answer("ap-depolarization", "A")
    prerequisite = observed_answer("resting-permeability", "K+", minute=1)
    assisted = observed_answer("ap-depolarization", "B", minute=2, assisted=True)
    independent = observed_answer("ap-depolarization", "B", minute=3)
    unclear = observed_answer("ap-depolarization", "I am not sure")
    report = EvidenceEvent(
        id="example:report",
        concept_id="action_potential_phases",
        kind="study_report",
        text="Potassium entering causes depolarization.",
        occurred_at=START,
        assessment="not_assessed",
        assistance="none",
        source="text",
    )
    # Only sample evidence is constructed; there are no memory writes or provider calls.
    cases = {
        "new-goal": ([], "transmitter_release", 1, None),
        "reported-confusion": ([report], "action_potential_phases", 1, report.text),
        "wrong-answer": ([miss], "action_potential_phases", 1, None),
        "prerequisite-checked": ([miss, prerequisite], "action_potential_phases", 1, None),
        "assisted-retry": ([miss, assisted], "action_potential_phases", 1, None),
        "independent-progress": ([miss, assisted, independent], "transmitter_release", 1, None),
        "unclear-answer": ([unclear], "action_potential_phases", 1, None),
        "due-review": ([miss], "transmitter_release", 24, None),
        "ambiguous-input": ([], "transmitter_release", 1, "Sodium and calcium"),
    }
    output = {}
    for name, (events, goal, hours, text) in cases.items():
        ctx = LearningContext(
            goal_concept_ids=[goal],
            concepts=CONCEPTS,
            items=CARDS,
            events=events,
            evaluated_at=START + timedelta(hours=hours),
        )
        semantic = (
            await interpret_safely(SemanticRequest(text=text, concepts=ctx.concepts, events=events))
            if text
            else None
        )
        decision = choose_learning_activities(ctx, semantic.interpretation if semantic else None)
        output[name] = {
            "semantic": semantic.model_dump(mode="json") if semantic else None,
            "decision": decision.model_dump(mode="json"),
        }
    return output


def main():
    parser = argparse.ArgumentParser(
        description="Inspect synthetic learning-policy scenarios without a database or model."
    )
    parser.add_argument("--scenario", help="Print only one named scenario.")
    parser.add_argument(
        "--json", action="store_true", help="Print full typed decisions and evidence as JSON."
    )
    args = parser.parse_args()
    examples = asyncio.run(run_examples())
    if args.scenario:
        if args.scenario not in examples:
            parser.error("Unknown scenario. Choose from: " + ", ".join(examples))
        examples = {args.scenario: examples[args.scenario]}
    if args.json:
        print(json.dumps(examples, indent=2))
        return
    for name, example in examples.items():
        decision = example["decision"]
        print(f"{name}: {decision['status']}")
        if decision["clarification"]:
            print(f"  {decision['clarification']}")
        for activity in decision["activities"]:
            print(f"  {activity['kind']} / {activity['concept_id']} / {activity['teaching_mode']}")
            print(f"    {activity['reason']}")


if __name__ == "__main__":
    main()
