# Source-bound graph discovery, v1

This implements B's next standalone feature on `pauline/source-graph-discovery`, based on the
learning-policy branch. It discovers document-scoped concepts and relationships instead of
loading the fixed neuroscience catalog. The HTTP/UI/database paths are not changed.

## Try it

```sh
uv sync --locked
.venv/bin/python -m loke_intelligence.source_graph_demo
.venv/bin/python -m loke_intelligence.source_graph_demo ./chapter.pdf --goal "Learn Action potential" --json
.venv/bin/python -m pytest tests/test_source_discovery.py
```

Default discovery is offline. The bundled Markdown excerpt is synthetic, authored to demonstrate
extraction cues; it is not a reviewed textbook or proof of general textbook extraction accuracy.
Its published `discovery-example.json` shows source → graph → cited reading plan.

Explicit `--live` opts into uploading selected source passages to OpenRouter using the existing
server environment configuration and billing. No live call was made during development. No web
search, URL fetching or pretrained fact text is added to the result. Failed/invalid model output
falls back to the same local source, never to the global catalog or outside material.

## Pipeline and ownership

1. `source_documents.py` reads bounded UTF-8 text/Markdown or selectable-text PDF and creates pages
   and passages. IDs include source-content hashes; page text and passage offsets are retained.
2. `source_extractors.py` defines the async GraphExtractor port, an English-pattern extractor and
   an optional one-call OpenRouter extractor. Both propose new concepts, typed edges and exact quotes.
3. `source_discovery.py` selects a bounded excerpt and validates proposals. The result contains
   concepts, relationships, source citations, goal references, coverage and warnings.
   `version` names the schema; `graph_hash` fingerprints the actual nodes/edges/citations,
   separately from the source-content hash, so changed extraction can be detected.
4. `source_learning.py` converts usable prerequisites into the adaptive policy context. Source
   provenance and inferred status remain visible in the resulting activity reasons.

B owns extraction/validation/learning decisions. C later persists documents, citations, graph
versions and learner-scoped records. A later provides upload/consent, goal clarification, source
navigation and uncertainty display. There is no new schema, global concept insert or fixture route.

## What counts as supported

Every label/alias must appear in its cited quotes. Each quote must exactly match a supplied
passage's start/end character span. Every relationship references discovered endpoints and cites
text mentioning them. A model can supply null offsets for a unique exact quote; code locates it.
Repeated quotes require explicit valid offsets, and incorrect offsets are never silently repaired.
Citation page, section and page offsets are assigned by code, not the model.
Offsets refer to extracted page text, not PDF bytes or visual bounding boxes. Text/Markdown have
one logical page; PDF page numbers are physical 1-based page indices. Markdown section headings
are preserved; PDF semantic sections are not guessed.

The local extractor recognizes headings, `Term (alias): definition`, and narrow explicit relation
cues such as `X is a prerequisite for Y`, `Before studying Y, understand X`, `X is related to Y`,
`X is part of Y`, and `X supports Y`. It is intentionally limited; ordinary prose without these
cues may need the model adapter or a clearer excerpt. There are no hardcoded neuroscience nodes.

Source-supported means the source explicitly states the recognized relationship, not that a human
reviewed its educational validity. Quote verification proves textual provenance, not semantic
entailment or scientific correctness. Model prerequisite claims without a recognized educational
cue are downgraded to inferred. Co-occurrence/scientific support is never automatically promoted
to a learning prerequisite. Model-proposed concepts absent from their quotes are rejected.

Inferred prerequisites may drive an explicitly tentative check/read recommendation, not a proven
gap or correctness update. `allow_inferred=False` excludes them from the policy view. Typed related,
part-of and supports edges remain in the graph but do not become prerequisites. Prerequisite
cycles/self-edges are retained as held proposals and excluded from planning; related cycles are
allowed. Explicit edges are considered before inferred edges, with deterministic ID tie order.

## Goal coverage and limits

Literal goal labels/aliases can resolve automatically. A model-only paraphrase mapping requires
confirmation. A missing goal in a completely inspected excerpt yields insufficient_source;
partial coverage instead asks for a relevant excerpt/clarification. No outside source is fetched.
No-concept extraction produces an honest no_concepts result. These statuses describe extraction
coverage and do not prove that a full textbook lacks a concept.

- Input: 5 MB, 50 PDF pages, 100,000 extracted characters, 200 passages; passage size at most 1,600 chars.
- Model/discovery view: at most 12 passages and 12,000 serialized characters, goal-relevance ranked.
  Inspected/omitted passage IDs and textless pages are explicit; nothing claims complete coverage
  when selection, graph caps or textless pages leave material unprocessed.
- Graph: at most 24 proposal concepts and 48 proposal edges. Duplicate normalized labels merge
  within this document; stable IDs are content/source scoped, not a global ontology.
- Model: one call, at most 2,500 output tokens, timeout up to 15s, strict schema, no automatic retry.
  Unknown IDs/quotes/fields and provider failures use local fallback; cancellation propagates.

Encrypted, malformed, unsupported, oversized and textless sources fail explicitly. No OCR, image,
table/formula interpretation or layout fidelity is promised. pypdf extracts text rather than
understanding PDF layout ([extraction documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)).
Per-page stream and total text guards reduce ordinary extraction size; decompression occurs before
the stream-size check, so this is not a hardened parser sandbox for hostile public uploads.

## Policy handoff

The adapter adds prerequisite metadata/citation IDs and enables reading fallback. Existing learning
contexts default to no metadata/no reading fallback, preserving the earlier algorithm behavior.
When all selected actions are reading, prerequisites are ordered before their dependents; diagnostic
question selection retains the earlier nearest-first policy.
Inference stays labeled on paths and reasons; source quotes support the explanation. `loke-source:`
locators are internal source references for a future reader, not hosted URLs or current UI routes.

Without authored assessment items, the plan offers cited source reading, not fabricated quizzes
or model-authorized grades. Completing reading records participation only; evidence remains
unchecked. An optional item bank must reference these document-scoped IDs and still uses the
supported deterministic grader. General generated-question evaluation is a separate feature.

## Remaining integration decisions

- C: document/learner scope, persistence/retention/deletion, version replacement and cross-document
  concept identity. Equal labels in different sources are not silently merged.
- A/B: source selection and provider-upload consent, goal confirmation, page/section reader links,
  and clear inferred/held/partial-coverage rendering.
- B/C: when inferred edges are eligible in production, graph/version commit guards, assessment-item
  authoring/review, and preserving existing evidence when a source changes.
- Source policy: how many documents can be selected, incremental expansion beyond excerpts, and
  handling contradictory sources. Open-web discovery is a separate future source mode.

All tests use synthetic source text/PDFs and injected model/HTTP fakes. Live-model discovery quality
and real textbook extraction still need separate evaluation; no paid calls or web learning-content
retrieval were used to demonstrate the feature.
