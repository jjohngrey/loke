"""Synthetic, offline orchestration scenarios; live routing is explicit opt-in."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from .learning_models import ActivityProgress
from .orchestration_models import (
    GraphRegistration,
    OrchestrationInput,
    RouteTarget,
    RoutingProposal,
    SubjectAssignment,
)
from .orchestration_openrouter import OpenRouterRoutingModel
from .orchestrator import GraphOrchestrator
from .source_discovery import discover_source_graph
from .source_documents import ingest_source

SCENARIOS = ("direct", "delegated", "physics", "ambiguous", "multi-graph", "repeated")


class ScriptedRouter:
    """Demo routing output, not a claim that a live model was evaluated."""

    def __init__(self, proposal):
        self.proposal = proposal

    async def route(self, request):
        return self.proposal


async def demo_graph(graph_id, foundation, goal):
    text = (
        f"## {foundation}\n{foundation}: a synthetic foundational concept.\n\n"
        f"## {goal}\n{goal}: a synthetic dependent concept.\n"
        f"{foundation} is a prerequisite for {goal}.\n"
    )
    document = ingest_source(text.encode(), f"{graph_id}.md")
    graph = await discover_source_graph(document, f"Understand {goal}")
    return GraphRegistration(graph_id=graph_id, document=document, graph=graph)


async def run_scenario(scenario="direct", *, live=False):
    physics = await demo_graph("physics-source", "Force", "Acceleration")
    chemistry = await demo_graph("chemistry-source", "Atom", "Molecule")
    graphs, text = [physics], "Acceleration"
    proposal = None
    selected = RouteTarget(
        graph_id=physics.graph_id, goal_concept_ids=physics.graph.goal_concept_ids
    )
    if scenario == "delegated":
        proposal = RoutingProposal(mode="delegate", targets=[selected])
    elif scenario == "physics":
        text = "Help me study physics"
        proposal = RoutingProposal(
            mode="direct",
            targets=[selected],
            subjects=[
                SubjectAssignment(
                    graph_id=physics.graph_id,
                    label="physics",
                    aliases=["mechanics"],
                    citation_ids=[physics.graph.citations[0].id],
                )
            ],
        )
    elif scenario == "ambiguous":
        graphs.append(await demo_graph("another-physics-source", "Force", "Acceleration"))
    elif scenario == "multi-graph":
        graphs, text = [physics, chemistry], "Acceleration and Molecule"
    request = OrchestrationInput(
        learner_scope="synthetic-learner",
        text=text,
        graphs=graphs,
        evaluated_at=datetime(2026, 10, 14, 4, tzinfo=UTC),
        study_minutes=10,
    )
    router = OpenRouterRoutingModel() if live else ScriptedRouter(proposal) if proposal else None
    orchestrator = GraphOrchestrator(router=router)
    first = await orchestrator.run(request)
    results = [first.model_dump(mode="json")]
    if scenario == "repeated":
        request.snapshots = first.snapshots
        if first.activities:
            request.graphs[0].progress = [
                ActivityProgress(
                    activity_id=first.activities[0].activity.activity_id,
                    status="completed",
                )
            ]
        results.append((await orchestrator.run(request)).model_dump(mode="json"))
    return {
        "scenario": scenario,
        "routing": "live" if live else "offline / scripted",
        "turns": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Send synthetic graph summaries to OpenRouter (billable).",
    )
    args = parser.parse_args()
    if args.live:
        load_dotenv(Path(__file__).resolve().parents[3] / ".env")

    async def scenarios():
        return [
            await run_scenario(name, live=args.live)
            for name in (SCENARIOS if args.scenario == "all" else (args.scenario,))
        ]

    results = asyncio.run(scenarios())
    if args.json:
        print(json.dumps(results, indent=2))
        return
    for result in results:
        print(f"{result['scenario']} ({result['routing']})")
        for number, turn in enumerate(result["turns"], 1):
            print(f"  Turn {number}: {turn['status']} / {turn['mode']} / {turn['routing_origin']}")
            if turn["clarification"]:
                print(f"    {turn['clarification']}")
            for planned in turn["activities"]:
                activity = planned["activity"]
                print(f"    {planned['graph_id']}: {activity['kind']} / {activity['minutes']} min")
                print(f"      {activity['reason']}")
                print(f"      Citations: {', '.join(activity['reason_source_ids'])}")
            for snapshot in turn["snapshots"]:
                print(f"    Memory: {snapshot['graph_id']} / {snapshot['specialist_id']}")
            for warning in turn["warnings"]:
                print(f"    Warning: {warning}")


if __name__ == "__main__":
    main()
