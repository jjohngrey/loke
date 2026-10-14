import asyncio
import json

import httpx
import pytest
from loke_contracts.catalog import CONCEPTS
from loke_contracts.models import SourceChunk
from loke_intelligence.learning_models import SemanticInterpretation, SemanticRequest
from loke_intelligence.semantic_openrouter import OpenRouterSemanticInterpreter
from loke_intelligence.semantics import interpret_safely


def request(text="I studied action potentials.", **changes):
    return SemanticRequest(text=text, concepts=CONCEPTS, **changes)


def interpretation():
    return dict(
        status="matched",
        concept_id="action_potential_phases",
        candidates=[{"concept_id": "action_potential_phases", "relevance": "strong"}],
        hypotheses=[],
        clarification=None,
    )


@pytest.mark.parametrize(
    "text,concept",
    [
        ("I studied action potentials.", "action_potential_phases"),
        ("What is resting membrane potential?", "resting_potential"),
        ("Explain selective permeability.", "selective_permeability"),
        ("presynaptic_calcium_entry", "presynaptic_calcium_entry"),
    ],
)
def test_aliases_and_canonical_ids(text, concept):
    result = asyncio.run(interpret_safely(request(text)))
    assert result.origin == "aliases"
    assert result.interpretation.concept_id == concept


@pytest.mark.parametrize("text", ["pumpkin", "channeling", "released software", "photography"])
def test_substrings_do_not_invent_concept_matches(text):
    result = asyncio.run(interpret_safely(request(text)))
    assert result.interpretation.status == "unmatched"
    assert result.interpretation.concept_id is None
    assert result.interpretation.clarification


def test_tied_meanings_stay_ambiguous_instead_of_catalog_first_match():
    result = asyncio.run(interpret_safely(request("Sodium and calcium")))
    assert result.interpretation.status == "ambiguous"
    assert result.interpretation.concept_id is None
    assert {c.concept_id for c in result.interpretation.candidates} == {
        "action_potential_phases",
        "presynaptic_calcium_entry",
    }


def test_possible_misconception_remains_a_hypothesis():
    result = asyncio.run(interpret_safely(request("Potassium entering causes depolarization.")))
    assert len(result.interpretation.hypotheses) == 1
    hypothesis = result.interpretation.hypotheses[0]
    assert "Possible" in hypothesis.description
    assert hypothesis.evidence_ids == []


@pytest.mark.parametrize(
    "text",
    [
        "Potassium entering does not cause depolarization.",
        "Does potassium entering cause depolarization?",
    ],
)
def test_negation_and_questions_do_not_assert_a_misconception(text):
    assert asyncio.run(interpret_safely(request(text))).interpretation.hypotheses == []


@pytest.mark.parametrize(
    "invalid", ["unknown_concept", "invented_event", "invented_source", "grade", "edge"]
)
def test_model_output_is_validated_and_falls_back_without_mutation(invalid):
    output = interpretation()
    if invalid == "unknown_concept":
        output["candidates"][0]["concept_id"] = output["concept_id"] = "invented"
    elif invalid in {"invented_event", "invented_source"}:
        output["hypotheses"] = [
            {
                "concept_id": "action_potential_phases",
                "description": "Possible confusion",
                "evidence_ids": ["invented"] if invalid == "invented_event" else [],
                "source_ids": ["invented"] if invalid == "invented_source" else [],
            }
        ]
    else:
        output[invalid] = "model must not authorize this"

    class FakeInterpreter:
        async def interpret(self, request):
            return output

    ctx = request()
    before = ctx.model_dump()
    result = asyncio.run(interpret_safely(ctx, FakeInterpreter()))
    assert result.origin == "fallback"
    assert result.interpretation.concept_id == "action_potential_phases"
    assert ctx.model_dump() == before


def test_valid_model_can_associate_a_paraphrase_without_learning_evidence():
    class FakeInterpreter:
        async def interpret(self, request):
            return SemanticInterpretation.model_validate(interpretation())

    ctx = request("How does the electrical spike rise so quickly?")
    assert asyncio.run(interpret_safely(ctx)).interpretation.status == "unmatched"
    result = asyncio.run(interpret_safely(ctx, FakeInterpreter()))
    assert result.origin == "model"
    assert result.interpretation.concept_id == "action_potential_phases"
    assert ctx.events == []


def test_provider_exception_and_timeout_use_local_fallback():
    class Failed:
        async def interpret(self, request):
            raise RuntimeError("private provider message")

    class Slow:
        async def interpret(self, request):
            await asyncio.sleep(1)

    for interpreter in (Failed(), Slow()):
        result = asyncio.run(interpret_safely(request(), interpreter, timeout_seconds=0.001))
        assert result.origin == "fallback"
        assert result.interpretation.concept_id == "action_potential_phases"
        assert "private" not in result.model_dump_json()


def test_cancellation_propagates_instead_of_producing_a_late_result():
    class Cancelled:
        async def interpret(self, request):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(interpret_safely(request(), Cancelled()))


def test_openrouter_adapter_uses_strict_schema_one_call_and_privacy_routing(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    calls = []

    def respond(req):
        calls.append(req)
        payload = json.loads(req.content)
        assert payload["provider"]["require_parameters"]
        assert payload["provider"]["data_collection"] == "deny"
        assert payload["max_tokens"] == 600
        schema = payload["response_format"]["json_schema"]["schema"]

        def check(value):
            if isinstance(value, dict):
                assert "default" not in value
                if value.get("type") == "object":
                    assert set(value["required"]) == set(value["properties"])
                    assert value["additionalProperties"] is False
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)

        check(schema)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(interpretation())}}]}
        )

    adapter = OpenRouterSemanticInterpreter(transport=httpx.MockTransport(respond))
    result = asyncio.run(interpret_safely(request(), adapter))
    assert result.origin == "model"
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["http", "malformed", "oversized", "missing_key"])
def test_live_adapter_failures_never_require_paid_calls(monkeypatch, failure):
    monkeypatch.setenv("OPENROUTER_API_KEY", "" if failure == "missing_key" else "test-only")
    calls = []

    def respond(req):
        calls.append(req)
        return httpx.Response(503 if failure == "http" else 200, json={"choices": []})

    ctx = request(
        sources=[SourceChunk(source_id="note-1", title="Untrusted note", text="x" * 13000)]
        if failure == "oversized"
        else []
    )
    result = asyncio.run(
        interpret_safely(ctx, OpenRouterSemanticInterpreter(httpx.MockTransport(respond)))
    )
    assert result.origin == "fallback"
    assert len(calls) == (0 if failure in {"oversized", "missing_key"} else 1)
