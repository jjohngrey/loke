import asyncio
import json
from datetime import UTC, datetime
from io import BytesIO

import httpx
import pytest
from loke_intelligence.learning_models import ActivityProgress
from loke_intelligence.source_discovery import discover_source_graph
from loke_intelligence.source_documents import SourceError, ingest_source
from loke_intelligence.source_extractors import OpenRouterGraphExtractor, PatternGraphExtractor
from loke_intelligence.source_learning import plan_from_source_graph
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

SAMPLE = """# Example learning excerpt

## Resting potential
Resting potential: the baseline voltage across a membrane.

## Action potential
Action potential (AP): a brief electrical signal.
Resting potential is a prerequisite for Action potential.

## Transmitter release
Transmitter release: chemical signaling between neurons.
Before studying Transmitter release, understand Action potential.
Action potential is related to Transmitter release.
"""
TIME = datetime(2026, 10, 17, 1, tzinfo=UTC)


def document(text=SAMPLE, filename="sample.md"):
    return ingest_source(text.encode(), filename)


def discover(doc=None, goal="Understand Transmitter release", extractor=None):
    return asyncio.run(discover_source_graph(doc or document(), goal, extractor))


def node(graph, label):
    return next(n for n in graph.concepts if n.label == label)


def make_pdf(pages, encrypted=False):
    """Small synthetic parser fixtures; not user document artifacts."""
    writer = PdfWriter()
    for lines in pages:
        page = writer.add_blank_page(width=600, height=700)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): writer._add_object(font),
                    }
                )
            }
        )
        stream = DecodedStreamObject()
        commands = ["BT /F1 12 Tf 40 660 Td"]
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.extend([f"({escaped}) Tj", "0 -20 Td"])
        commands.append("ET")
        stream.set_data("\n".join(commands).encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_source_offsets_sections_and_content_ids_are_stable():
    doc = document()
    assert doc == document()
    for passage in doc.passages:
        assert doc.pages[passage.page - 1].text[passage.start : passage.end] == passage.text
    assert {p.section for p in doc.passages} >= {"Action potential", "Resting potential"}
    assert document(SAMPLE + "\nNew content").id != doc.id
    assert document(filename="different-name.md").id == doc.id


def test_pdf_extraction_preserves_page_citations_and_no_outside_catalog():
    data = make_pdf(
        [
            ["Electric signal: a brief electrical event."],
            [
                "Chemical signal: communication using molecules.",
                "Electric signal is a prerequisite for Chemical signal.",
            ],
        ]
    )
    doc = ingest_source(data, "example.pdf")
    graph = discover(doc, "Learn Chemical signal")
    assert graph.status == "ready"
    assert {n.label for n in graph.concepts} == {"Electric signal", "Chemical signal"}
    edge = next(e for e in graph.relations if e.kind == "prerequisite_of")
    quote = next(q for q in graph.citations if q.id in edge.citation_ids)
    assert quote.page == 2
    assert doc.pages[1].text[quote.start : quote.end] == quote.quote


@pytest.mark.parametrize(
    "data,name",
    [
        (b"", "empty.txt"),
        (b"x" * 5_000_001, "large.txt"),
        (b"\xff", "wrong.txt"),
        (b"a\x00b", "binary.txt"),
        (b"not pdf", "fake.pdf"),
        (b"text", "photo.png"),
        (b"x" * 100_001, "long.md"),
        (b"  \n", "blank.txt"),
    ],
)
def test_unsupported_sources_fail_honestly(data, name):
    with pytest.raises(SourceError):
        ingest_source(data, name)


def test_encrypted_and_textless_pdfs_are_rejected_without_ocr_claims():
    with pytest.raises(SourceError, match="Encrypted"):
        ingest_source(make_pdf([["Secret content"]], encrypted=True), "private.pdf")
    with pytest.raises(SourceError, match="No extractable text"):
        ingest_source(make_pdf([[]]), "textless.pdf")


def test_pdf_resource_limits_and_partial_text_coverage(monkeypatch):
    import loke_intelligence.source_documents as extraction

    with pytest.raises(SourceError, match="50 pages"):
        ingest_source(make_pdf([[] for _ in range(51)]), "long.pdf")
    monkeypatch.setattr(extraction, "MAX_PAGE_STREAM_BYTES", 5)
    with pytest.raises(SourceError, match="page content"):
        ingest_source(make_pdf([["Too much content"]]), "stream.pdf")
    monkeypatch.setattr(extraction, "MAX_PAGE_STREAM_BYTES", 2_000_000)
    doc = ingest_source(make_pdf([["Signal: a brief event."], []]), "mixed.pdf")
    graph = discover(doc, "Learn Signal")
    assert doc.textless_pages == [2]
    assert "pages_without_extractable_text" in graph.warnings


def test_discovered_nodes_edges_and_quotes_are_grounded_in_source():
    doc = document()
    graph = discover(doc)
    assert graph.status == "ready"
    assert graph.source_only
    assert node(graph, "Action potential").aliases == ["AP"]
    assert graph.goal_concept_ids == [node(graph, "Transmitter release").id]
    assert len([e for e in graph.relations if e.kind == "prerequisite_of"]) == 2
    for citation in graph.citations:
        assert doc.pages[citation.page - 1].text[citation.start : citation.end] == citation.quote
    assert {n.id for n in graph.concepts}.isdisjoint(
        {"action_potential_phases", "resting_potential"}
    )
    assert graph == discover(doc)


def test_missing_goal_never_fetches_or_seeds_outside_knowledge():
    graph = discover(goal="Learn quantum entanglement")
    assert graph.status == "insufficient_source"
    assert graph.goal_concept_ids == []
    assert "quantum" not in " ".join(n.label for n in graph.concepts)
    with pytest.raises(ValueError, match="clarification"):
        plan_from_source_graph(document(), graph, TIME)


def test_canonicalization_merges_case_duplicates_and_deduplicates_relations():
    graph = discover(
        document(
            "Signal: a message.\nsignal: information.\nSignal is related to Message.\nMessage is related to Signal.\n"
        ),
        "Learn Signal",
    )
    assert len([n for n in graph.concepts if n.label.lower() == "signal"]) == 1
    assert len(graph.relations) == 1
    assert len(graph.relations[0].citation_ids) == 2


def test_prerequisite_cycles_are_held_but_related_cycles_remain_usable():
    graph = discover(
        document(
            "Alpha is a prerequisite for Beta.\nBeta is a prerequisite for Alpha.\nAlpha is related to Beta.\n"
        ),
        "Learn Beta",
    )
    held = [e for e in graph.relations if not e.usable]
    assert len(held) == 1
    assert held[0].held_reason == "cycle"
    assert all(e.usable for e in graph.relations if e.kind == "related_to")
    assert "relationships_held_out_of_policy_graph" in graph.warnings
    plan_from_source_graph(
        document(
            "Alpha is a prerequisite for Beta.\nBeta is a prerequisite for Alpha.\nAlpha is related to Beta.\n"
        ),
        graph,
        TIME,
    )


@pytest.mark.parametrize(
    "damage", ["quote", "offset", "passage", "concept", "alias", "edge", "grade"]
)
def test_invalid_model_discoveries_fall_back_without_invented_content(damage):
    class Invalid:
        async def extract(self, request):
            proposal = await PatternGraphExtractor().extract(request)
            if damage == "quote":
                proposal.concepts[0].citations[0].quote = "invented quotation"
            elif damage == "offset":
                proposal.concepts[0].citations[0].start += 1
            elif damage == "passage":
                proposal.concepts[0].citations[0].passage_id = "outside-source"
            elif damage == "concept":
                proposal.concepts[0].label = "Quantum entanglement"
            elif damage == "alias":
                proposal.concepts[0].aliases = ["invented alias"]
            elif damage == "edge":
                proposal.relations[0].from_key = "outside-source"
            else:
                return {**proposal.model_dump(), "grade": "correct"}
            return proposal

    graph = discover(extractor=Invalid())
    assert graph.origin == "fallback"
    assert "model_invalid_or_unavailable" in graph.warnings
    assert graph.concepts == discover().concepts


def test_model_paraphrase_goal_requires_confirmation_and_keeps_source_scope():
    class Paraphrase:
        async def extract(self, request):
            proposal = await PatternGraphExtractor().extract(request)
            proposal.goal_keys = [
                n.key for n in proposal.concepts if n.label == "Transmitter release"
            ]
            return proposal

    graph = discover(goal="How do neurons communicate chemically?", extractor=Paraphrase())
    assert graph.origin == "model"
    assert graph.status == "needs_clarification"
    assert graph.goal_concept_ids == []


def test_cooccurrence_is_not_automatically_a_prerequisite():
    graph = discover(
        document("Alpha: one idea.\nBeta: another idea.\nAlpha and Beta occur in this chapter.\n"),
        "Learn Beta",
    )
    assert graph.relations == []


def test_inferred_model_edge_is_labeled_in_policy_and_can_be_excluded():
    text = "Alpha: an introductory idea.\nBeta: an advanced idea.\nAlpha supports Beta.\n"
    doc = document(text)

    class Inferred:
        async def extract(self, request):
            proposal = await PatternGraphExtractor().extract(request)
            proposal.relations[0].kind = "prerequisite_of"
            # Claiming source support does not promote a noneducational support statement.
            return proposal

    graph = discover(doc, "Learn Beta", Inferred())
    edge = graph.relations[0]
    assert edge.basis == "inferred"
    assert "relationship_claim_downgraded_to_inference" in graph.warnings
    plan = plan_from_source_graph(doc, graph, TIME)
    first = plan.activities[0]
    assert first.concept_id == node(graph, "Alpha").id
    assert first.reason_code == "inferred_prerequisite"
    assert "inferred" in first.reason
    assert first.prerequisite_edge_ids == [edge.id]
    assert set(edge.citation_ids) <= set(first.reason_source_ids)
    assert all(s.status == "unchecked" for s in plan.evidence)
    excluded = plan_from_source_graph(doc, graph, TIME, allow_inferred=False)
    assert excluded.activities[0].concept_id == node(graph, "Beta").id


def test_source_to_graph_to_plan_is_cited_reading_without_fabricated_quizzes():
    doc, graph = document(), discover()
    plan = plan_from_source_graph(doc, graph, TIME)
    assert plan.activities[0].concept_id == node(graph, "Resting potential").id
    assert all(a.kind == "learn" and a.card is None for a in plan.activities)
    assert all(a.support_text and a.reason_source_ids for a in plan.activities)
    assert all(s.status == "unchecked" for s in plan.evidence)
    assert sum(a.minutes for a in plan.activities) <= 10
    assert all(a.resource_url.startswith("loke-source:") for a in plan.activities)
    progress = [
        ActivityProgress(activity_id=a.activity_id, status="completed") for a in plan.activities
    ]
    next_plan = plan_from_source_graph(doc, graph, TIME, progress=progress)
    assert set(a.activity_id for a in next_plan.activities).isdisjoint(
        {p.activity_id for p in progress}
    )
    assert all(s.status == "unchecked" for s in next_plan.evidence)
    with pytest.raises(ValueError, match="different source"):
        plan_from_source_graph(document(SAMPLE + "New material"), graph, TIME)


def test_large_source_reports_coverage_limits_instead_of_claiming_absence():
    doc = document("\n\n".join(f"Topic {i}: " + "other material " * 80 for i in range(20)))
    graph = discover(doc, "Learn unavailable topic")
    assert graph.omitted_passage_ids
    assert "partial_source_coverage" in graph.warnings
    assert graph.status == "needs_clarification"


def test_timeout_and_cancellation_are_honest():
    class Slow:
        async def extract(self, request):
            await asyncio.sleep(1)

    graph = asyncio.run(
        discover_source_graph(document(), "Learn Action potential", Slow(), timeout_seconds=0.001)
    )
    assert graph.origin == "fallback"

    class Cancelled:
        async def extract(self, request):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        discover(extractor=Cancelled())


def test_model_adapter_is_single_call_with_strict_source_only_prompt(monkeypatch):
    import json

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    calls = []

    async def exercise():
        def respond(req):
            calls.append(req)
            payload = json.loads(req.content)
            assert payload["provider"]["data_collection"] == "deny"
            assert payload["provider"]["require_parameters"]
            assert "ONLY supplied passages" in payload["messages"][0]["content"]
            assert payload["response_format"]["json_schema"]["strict"]
            assert "tools" not in payload
            request_text = payload["messages"][1]["content"]
            assert len(request_text) <= 12000
            return httpx.Response(200, json={"choices": [{"message": {"content": response}}]})

        # Produce a valid response from the same bounded request before injecting the transport.
        from loke_intelligence.source_discovery import select_request

        request = select_request(document(), "Understand Transmitter release")
        response = (await PatternGraphExtractor().extract(request)).model_dump_json()
        return await discover_source_graph(
            document(), request.goal, OpenRouterGraphExtractor(httpx.MockTransport(respond))
        )

    assert asyncio.run(exercise()).origin == "model"
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["missing_key", "http", "invalid_json"])
def test_live_failures_use_source_only_fallback_without_paid_calls(monkeypatch, failure):
    monkeypatch.setenv("OPENROUTER_API_KEY", "" if failure == "missing_key" else "test-only")
    calls = []

    def respond(req):
        calls.append(req)
        return httpx.Response(503 if failure == "http" else 200, json={"choices": []})

    graph = discover(extractor=OpenRouterGraphExtractor(httpx.MockTransport(respond)))
    assert graph.origin == "fallback"
    assert len(calls) == (0 if failure == "missing_key" else 1)


def test_model_cannot_mutate_the_source_request_into_new_facts():
    doc = document()
    original = doc.model_dump_json()

    class Mutating:
        async def extract(self, request):
            request.passages[0].text = "# Invented outside-source topic"
            return await PatternGraphExtractor().extract(request)

    graph = discover(doc, extractor=Mutating())
    assert graph.origin == "fallback"
    assert doc.model_dump_json() == original
    assert "Invented" not in " ".join(n.label for n in graph.concepts)


def test_no_concepts_is_not_reported_as_success():
    graph = discover(
        document("This paragraph has no explicit extraction cues."), "Learn new concepts"
    )
    assert graph.status == "no_concepts"
    assert graph.goal_concept_ids == []
    assert graph.clarification


def test_graph_hash_changes_with_extraction_even_when_source_is_unchanged():
    class Subset:
        async def extract(self, request):
            result = await PatternGraphExtractor().extract(request)
            result.relations = []
            return result

    baseline, subset = discover(), discover(extractor=Subset())
    assert subset.content_hash == baseline.content_hash
    assert subset.graph_hash != baseline.graph_hash


def test_passage_and_graph_caps_report_partial_coverage(monkeypatch):
    import loke_intelligence.source_documents as extraction

    monkeypatch.setattr(extraction, "MAX_PASSAGES", 2)
    with pytest.raises(SourceError, match="200 passages"):
        document()
    monkeypatch.setattr(extraction, "MAX_PASSAGES", 200)
    text = "\n".join(f"Topic {i}: a concept." for i in range(30))
    graph = discover(document(text), "Learn Topic 29")
    assert len(graph.concepts) <= 24
    assert "graph_limits_reached" in graph.warnings
    assert graph.status == "ready"


def test_published_example_matches_read_only_demo():
    from loke_intelligence.source_graph_demo import EXAMPLE, inspect_source

    expected = json.loads((EXAMPLE.parent / "discovery-example.json").read_text())
    result = asyncio.run(inspect_source(EXAMPLE, "Understand Transmitter release"))
    assert result == expected
    assert (
        result["decision"]["activities"][0]["concept_id"]
        == node(discover(), "Resting potential").id
    )


def test_unique_model_quotes_can_be_anchored_by_code():
    class Quoting:
        async def extract(self, request):
            proposal = await PatternGraphExtractor().extract(request)
            for concept in proposal.concepts:
                for citation in concept.citations:
                    citation.start = citation.end = None
            for edge in proposal.relations:
                for citation in edge.citations:
                    citation.start = citation.end = None
            return proposal

    graph = discover(extractor=Quoting())
    assert graph.origin == "model"
    assert graph.citations == discover().citations


def test_repeated_quotes_require_disambiguating_offsets():
    doc = document("Alpha: a concept.\nAlpha: a concept.\n")

    class AmbiguousQuote:
        async def extract(self, request):
            proposal = await PatternGraphExtractor().extract(request)
            proposal.concepts[0].citations[0].start = None
            proposal.concepts[0].citations[0].end = None
            return proposal

    graph = discover(doc, "Learn Alpha", AmbiguousQuote())
    assert graph.origin == "fallback"
    assert len(graph.citations) == 2
