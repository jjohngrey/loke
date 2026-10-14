"""Inspect a document -> graph -> learning plan without a database or seed catalog."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from .source_discovery import discover_source_graph
from .source_documents import SourceError, read_source
from .source_extractors import OpenRouterGraphExtractor
from .source_learning import plan_from_source_graph

EXAMPLE = (
    Path(__file__).resolve().parents[3] / "shared/fixtures/source-graph/v1/learning-excerpt.md"
)


async def inspect_source(path, goal, *, live=False):
    document = read_source(path)
    graph = await discover_source_graph(
        document, goal, OpenRouterGraphExtractor() if live else None
    )
    decision = (
        plan_from_source_graph(document, graph, datetime.now(UTC))
        if graph.status == "ready"
        else None
    )
    return {
        "document": {"id": document.id, "title": document.title, "kind": document.kind},
        "graph": graph.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json") if decision else None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Discover a cited, source-only graph from a text/Markdown/PDF excerpt."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(EXAMPLE),
        help="Local source; defaults to the synthetic example.",
    )
    parser.add_argument("--goal", default="Understand Transmitter release")
    parser.add_argument(
        "--json", action="store_true", help="Print graph, exact citations and policy decision."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Opt in to sending selected source text to OpenRouter (billable); no web retrieval.",
    )
    args = parser.parse_args()
    if args.live:
        load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    try:
        result = asyncio.run(inspect_source(args.path, args.goal, live=args.live))
    except SourceError as exc:
        parser.error(str(exc))
    except OSError:
        parser.error("The local source file could not be read.")
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, indent=2))
        return
    graph = result["graph"]
    print(f"{result['document']['title']}: {graph['status']} ({graph['origin']}, source-only)")
    print(
        f"Inspected {len(graph['inspected_passage_ids'])} passages; omitted {len(graph['omitted_passage_ids'])}."
    )
    nodes = {node["id"]: node["label"] for node in graph["concepts"]}
    print("Concepts: " + ", ".join(nodes.values()))
    for edge in graph["relations"]:
        label = edge["basis"] if edge["usable"] else f"held: {edge['held_reason']}"
        print(f"  {nodes[edge['from_id']]} --{edge['kind']}--> {nodes[edge['to_id']]} [{label}]")
    if graph["clarification"]:
        print(graph["clarification"])
    for warning in graph["warnings"]:
        print(f"Warning: {warning}")
    if result["decision"]:
        print("Next activities:")
        for activity in result["decision"]["activities"]:
            print(
                f"  {activity['kind']} / {nodes[activity['concept_id']]} / {activity['minutes']} min"
            )
            print(f"    {activity['reason']}")
            print(f"    Citation IDs: {', '.join(activity['reason_source_ids'])}")


if __name__ == "__main__":
    main()
