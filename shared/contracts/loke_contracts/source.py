"""Source-scoped discovery models; no global catalog or learner-state writes."""

from typing import Literal

from pydantic import Field

from loke_contracts.models import Contract


class SourcePage(Contract):
    number: int = Field(ge=1)
    text: str


class SourcePassage(Contract):
    id: str
    page: int
    section: str | None
    start: int
    end: int
    text: str


class SourceDocument(Contract):
    id: str
    title: str
    kind: Literal["text", "markdown", "pdf"]
    content_hash: str
    pages: list[SourcePage]
    passages: list[SourcePassage]
    textless_pages: list[int] = Field(default_factory=list)


class QuoteProposal(Contract):
    passage_id: str
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)
    quote: str = Field(min_length=1, max_length=1600)


class ConceptProposal(Contract):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    label: str = Field(min_length=2, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=6)
    citations: list[QuoteProposal] = Field(min_length=1, max_length=3)


class RelationProposal(Contract):
    from_key: str
    to_key: str
    kind: Literal["prerequisite_of", "related_to", "part_of", "supports"]
    basis: Literal["source_supported", "inferred"]
    citations: list[QuoteProposal] = Field(min_length=1, max_length=3)


class GraphProposal(Contract):
    concepts: list[ConceptProposal] = Field(max_length=24)
    relations: list[RelationProposal] = Field(default_factory=list, max_length=48)
    goal_keys: list[str] = Field(default_factory=list, max_length=3)
    truncated: bool = False


class DiscoveryRequest(Contract):
    document_id: str
    goal: str = Field(min_length=3, max_length=500)
    passages: list[SourcePassage]


class SourceCitation(Contract):
    id: str
    document_id: str
    passage_id: str
    page: int
    section: str | None
    start: int
    end: int
    quote: str


class DiscoveredConcept(Contract):
    id: str
    label: str
    aliases: list[str]
    citation_ids: list[str]


class DiscoveredRelation(Contract):
    id: str
    from_id: str
    to_id: str
    kind: Literal["prerequisite_of", "related_to", "part_of", "supports"]
    basis: Literal["source_supported", "inferred"]
    origin: Literal["patterns", "model"]
    citation_ids: list[str]
    usable: bool
    held_reason: Literal["cycle", "self_relation"] | None = None


class SourceGraph(Contract):
    version: Literal["source-graph-v1"] = "source-graph-v1"
    graph_hash: str
    document_id: str
    content_hash: str
    source_only: Literal[True] = True
    status: Literal["ready", "needs_clarification", "insufficient_source", "no_concepts"]
    origin: Literal["patterns", "model", "fallback"]
    concepts: list[DiscoveredConcept]
    relations: list[DiscoveredRelation]
    citations: list[SourceCitation]
    goal_concept_ids: list[str]
    inspected_passage_ids: list[str]
    omitted_passage_ids: list[str]
    clarification: str | None = None
    warnings: list[str] = Field(default_factory=list)
