"""Validate extractor proposals and assemble a bounded, cited, source-only graph."""

import asyncio
import hashlib
import json

from .source_extractors import (
    GraphExtractor,
    PatternGraphExtractor,
    explicit_relations,
    mentions,
    normalize,
)
from .source_models import (
    DiscoveredConcept,
    DiscoveredRelation,
    DiscoveryRequest,
    GraphProposal,
    SourceCitation,
    SourceDocument,
    SourceGraph,
)


def identifier(kind: str, *parts: str) -> str:
    digest = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]
    return f"{kind}:{digest}"


def select_request(document: SourceDocument, goal: str) -> DiscoveryRequest:
    base = DiscoveryRequest(document_id=document.id, goal=goal, passages=[])
    words = set(normalize(goal).split()) - {
        "learn",
        "understand",
        "explain",
        "about",
        "how",
        "the",
        "a",
        "and",
        "of",
        "to",
    }
    ranked = sorted(
        enumerate(document.passages),
        key=lambda pair: (
            -len(words & set(normalize(pair[1].text).split())),
            pair[0],
        ),
    )
    chosen = []
    for index, passage in ranked:
        trial = [*base.passages, passage]
        if (
            len(trial) > 12
            or len(base.model_copy(update={"passages": trial}).model_dump_json()) > 12000
        ):
            continue
        base.passages = trial
        chosen.append(index)
    base.passages = [document.passages[i] for i in sorted(chosen)]
    return base


def assemble_graph(
    document: SourceDocument, request: DiscoveryRequest, proposal: GraphProposal, origin: str
) -> SourceGraph:
    proposal = GraphProposal.model_validate(proposal.model_dump())
    document_passages = {p.id: p for p in document.passages}
    pages = {p.number: p.text for p in document.pages}
    if request.document_id != document.id or any(
        document_passages.get(p.id) != p for p in request.passages
    ):
        raise ValueError("Discovery request must use this document's original passages.")
    proposals = {node.key: node for node in proposal.concepts}
    if len(proposals) != len(proposal.concepts) or not set(proposal.goal_keys) <= proposals.keys():
        raise ValueError("Duplicate concept keys or unknown goal references.")
    passages = {p.id: p for p in request.passages}
    citations = {}

    def cite(quote):
        passage = passages.get(quote.passage_id)
        if passage is None:
            raise ValueError("Citation references an unavailable passage.")
        start, end = quote.start, quote.end
        if start is None and end is None:
            start = passage.text.find(quote.quote)
            if start < 0 or passage.text.find(quote.quote, start + 1) >= 0:
                raise ValueError("Quote needs an exact, unique anchor or explicit valid offsets.")
            end = start + len(quote.quote)
        if (
            start is None
            or end is None
            or start < 0
            or end <= start
            or passage.text[start:end] != quote.quote
        ):
            raise ValueError("Citation must match an exact span of a supplied passage.")
        if end > len(passage.text):
            raise ValueError("Citation offsets exceed the supplied passage.")
        if pages[passage.page][passage.start + start : passage.start + end] != quote.quote:
            raise ValueError("Citation must match the original extracted page text.")
        cid = identifier("citation", document.id, passage.id, str(start), str(end), quote.quote)
        citations[cid] = SourceCitation(
            id=cid,
            document_id=document.id,
            passage_id=passage.id,
            page=passage.page,
            section=passage.section,
            start=passage.start + start,
            end=passage.start + end,
            quote=quote.quote,
        )
        return cid

    concepts, mapping = {}, {}
    for node in proposal.concepts:
        quote_texts = [q.quote for q in node.citations]
        for term in [node.label, *node.aliases]:
            if not any(mentions(term, text) for text in quote_texts):
                raise ValueError(
                    "Concept labels and aliases must occur in their cited source quotes."
                )
        node_id = identifier("concept", document.id, normalize(node.label))
        mapping[node.key] = node_id
        refs = [cite(q) for q in node.citations]
        if node_id in concepts:
            existing = concepts[node_id]
            existing.aliases = sorted(set([*existing.aliases, *node.aliases]))
            existing.citation_ids = sorted(set([*existing.citation_ids, *refs]))
        else:
            concepts[node_id] = DiscoveredConcept(
                id=node_id,
                label=node.label,
                aliases=sorted(set(node.aliases)),
                citation_ids=sorted(set(refs)),
            )
    edges = {}
    warnings = []
    for edge in proposal.relations:
        if edge.from_key not in proposals or edge.to_key not in proposals:
            raise ValueError("Relationship references an unknown source concept.")
        left, right = proposals[edge.from_key], proposals[edge.to_key]
        for endpoint in (left, right):
            if not any(
                mentions(term, q.quote)
                for term in [endpoint.label, *endpoint.aliases]
                for q in edge.citations
            ):
                raise ValueError("Relationship citations must mention both endpoints.")
        refs = [cite(q) for q in edge.citations]
        supported = any(
            kind == edge.kind
            and normalize(a) in {normalize(t) for t in [left.label, *left.aliases]}
            and normalize(b) in {normalize(t) for t in [right.label, *right.aliases]}
            for quote in edge.citations
            for a, b, kind in explicit_relations(quote.quote)
        )
        basis = "source_supported" if edge.basis == "source_supported" and supported else "inferred"
        if basis != edge.basis:
            warnings.append("relationship_claim_downgraded_to_inference")
        a, b = mapping[edge.from_key], mapping[edge.to_key]
        if edge.kind == "related_to":
            a, b = sorted((a, b))
        eid = identifier("edge", document.id, a, b, edge.kind)
        if eid in edges:
            existing = edges[eid]
            existing.citation_ids = sorted(set([*existing.citation_ids, *refs]))
            if basis == "source_supported":
                existing.basis = basis
        else:
            edges[eid] = DiscoveredRelation(
                id=eid,
                from_id=a,
                to_id=b,
                kind=edge.kind,
                basis=basis,
                origin=origin,
                citation_ids=sorted(set(refs)),
                usable=True,
            )
    adjacency = {cid: set() for cid in concepts}

    def reaches(start, target):
        stack, seen = [start], set()
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                stack.extend(adjacency[current])
        return False

    # Retain held proposals for inspection; only the prerequisite view must be acyclic.
    for edge in sorted(edges.values(), key=lambda e: (e.basis != "source_supported", e.id)):
        if edge.from_id == edge.to_id:
            edge.usable, edge.held_reason = False, "self_relation"
        elif edge.kind == "prerequisite_of":
            if reaches(edge.to_id, edge.from_id):
                edge.usable, edge.held_reason = False, "cycle"
            else:
                adjacency[edge.from_id].add(edge.to_id)
    literal_goals = [
        node.id
        for node in concepts.values()
        if any(mentions(t, request.goal) for t in [node.label, *node.aliases])
    ]
    proposed_goals = list(dict.fromkeys(mapping[key] for key in proposal.goal_keys))
    inspected = {p.id for p in request.passages}
    omitted = [p.id for p in document.passages if p.id not in inspected]
    incomplete = bool(omitted or document.textless_pages or proposal.truncated)
    if omitted:
        warnings.append("partial_source_coverage")
    if document.textless_pages:
        warnings.append("pages_without_extractable_text")
    if proposal.truncated:
        warnings.append("graph_limits_reached")
    if any(not edge.usable for edge in edges.values()):
        warnings.append("relationships_held_out_of_policy_graph")
    if literal_goals:
        status, clarification, goals = "ready", None, sorted(set(literal_goals))
    elif proposed_goals:
        status, clarification, goals = (
            "needs_clarification",
            "Confirm which extracted concept matches your goal before planning.",
            [],
        )
    elif not concepts:
        status, clarification, goals = (
            "no_concepts",
            "No supported concepts were extracted; try a clearer source excerpt.",
            [],
        )
    elif incomplete:
        status, clarification, goals = (
            "needs_clarification",
            "The inspected excerpt did not cover the goal. Select a relevant section or clarify the goal.",
            [],
        )
    else:
        status, clarification, goals = (
            "insufficient_source",
            "The supplied excerpt does not identify the goal concept. Provide more source material or clarify the goal.",
            [],
        )
    ordered_concepts = sorted(concepts.values(), key=lambda n: (normalize(n.label), n.id))
    ordered_relations = sorted(edges.values(), key=lambda e: e.id)
    ordered_citations = sorted(citations.values(), key=lambda q: q.id)
    graph_hash = hashlib.sha256(
        json.dumps(
            {
                "version": "source-graph-v1",
                "document_id": document.id,
                "concepts": [n.model_dump() for n in ordered_concepts],
                "relations": [e.model_dump() for e in ordered_relations],
                "citations": [q.model_dump() for q in ordered_citations],
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return SourceGraph(
        graph_hash=graph_hash,
        document_id=document.id,
        content_hash=document.content_hash,
        status=status,
        origin=origin,
        concepts=ordered_concepts,
        relations=ordered_relations,
        citations=ordered_citations,
        goal_concept_ids=goals,
        inspected_passage_ids=[p.id for p in request.passages],
        omitted_passage_ids=omitted,
        clarification=clarification,
        warnings=sorted(set(warnings)),
    )


async def discover_source_graph(
    document: SourceDocument,
    goal: str,
    extractor: GraphExtractor | None = None,
    timeout_seconds: float = 15,
) -> SourceGraph:
    if not 0 < timeout_seconds <= 15:
        raise ValueError("Graph discovery timeout must be between zero and 15 seconds.")
    request = select_request(document, goal)
    if extractor:
        try:
            raw = await asyncio.wait_for(
                extractor.extract(request.model_copy(deep=True)), timeout_seconds
            )
            graph = assemble_graph(document, request, GraphProposal.model_validate(raw), "model")
            return graph
        except Exception:
            # No outside facts, hidden retry or unsafe provider detail is added on failure.
            pass
    proposal = await PatternGraphExtractor().extract(request)
    graph = assemble_graph(document, request, proposal, "patterns")
    if extractor:
        graph.origin = "fallback"
        graph.warnings.append("model_invalid_or_unavailable")
    return graph
