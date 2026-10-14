"""Meaning association proposes context; it never writes evidence or graph relations."""

import asyncio
import re
from typing import Protocol

from .learning_models import (
    InterpretationResult,
    MisconceptionHypothesis,
    SemanticCandidate,
    SemanticInterpretation,
    SemanticRequest,
)


class SemanticInterpreter(Protocol):
    async def interpret(self, request: SemanticRequest) -> SemanticInterpretation: ...


def tokens(text: str) -> list[str]:
    # Explicit inflections for this small catalog; no substring matches such as pump/pumpkin.
    plurals = {
        "potentials": "potential",
        "gradients": "gradient",
        "channels": "channel",
        "neurons": "neuron",
        "vesicles": "vesicle",
        "ions": "ion",
    }
    return [plurals.get(word, word) for word in re.findall(r"[a-z0-9]+", text.lower())]


def contains(words: list[str], phrase: list[str]) -> bool:
    return any(words[i : i + len(phrase)] == phrase for i in range(len(words) - len(phrase) + 1))


class AliasInterpreter:
    async def interpret(self, request: SemanticRequest) -> SemanticInterpretation:
        words = tokens(request.text)
        ranked = []
        for order, concept in enumerate(request.concepts):
            phrases = {
                tuple(tokens(p.replace("_", " ")))
                for p in [concept.id, concept.label, *concept.aliases]
            }
            matched = [phrase for phrase in phrases if phrase and contains(words, list(phrase))]
            if matched:
                # Specific multiword phrases outrank isolated generic terms. Ties stay unresolved.
                score = (max(map(len, matched)), sum(map(len, matched)))
                ranked.append((score, order, concept.id))
        ranked.sort(key=lambda entry: (tuple(-n for n in entry[0]), entry[1]))
        candidates = [
            SemanticCandidate(concept_id=cid, relevance="strong" if score[0] >= 2 else "weak")
            for score, _, cid in ranked[:3]
        ]
        if not ranked:
            return SemanticInterpretation(
                status="unmatched",
                concept_id=None,
                candidates=[],
                clarification="Which neural-signaling concept do you want to discuss?",
            )
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            return SemanticInterpretation(
                status="ambiguous",
                concept_id=None,
                candidates=candidates,
                clarification="Which of these concepts should we focus on first?",
            )
        concept_id = ranked[0][2]
        hypotheses = []
        # Narrow demo cue, always phrased as a hypothesis. Negation/questions are not assertions.
        assertion = re.search(
            r"\bpotassium (?:entering|enters|influx)\b.*\b(?:causes?|drives?)\b.*\bdepolari[sz]ation\b",
            request.text.lower(),
        )
        uncertain = re.search(
            r"\b(?:not|never|doesn't|does not|isn't|whether)\b|\?", request.text.lower()
        )
        if concept_id == "action_potential_phases" and assertion and not uncertain:
            hypotheses.append(
                MisconceptionHypothesis(
                    concept_id=concept_id,
                    description="Possible confusion about which ion movement drives depolarization; check with an item.",
                    evidence_ids=[
                        e.id
                        for e in request.events
                        if e.kind == "study_report" and e.text == request.text
                    ],
                )
            )
        return SemanticInterpretation(
            status="matched", concept_id=concept_id, candidates=candidates, hypotheses=hypotheses
        )


def validate_interpretation(value: SemanticInterpretation, request: SemanticRequest) -> None:
    allowed = {c.id for c in request.concepts}
    referenced = {c.concept_id for c in value.candidates} | {h.concept_id for h in value.hypotheses}
    if value.concept_id:
        referenced.add(value.concept_id)
    if not referenced <= allowed:
        raise ValueError("Semantic output referenced an unknown concept.")
    events = {e.id for e in request.events}
    sources = {s.source_id for s in request.sources}
    for hypothesis in value.hypotheses:
        if not set(hypothesis.evidence_ids) <= events or not set(hypothesis.source_ids) <= sources:
            raise ValueError("Semantic output referenced unavailable evidence or sources.")


async def interpret_safely(
    request: SemanticRequest,
    interpreter: SemanticInterpreter | None = None,
    timeout_seconds: float = 15,
) -> InterpretationResult:
    if not 0 < timeout_seconds <= 15:
        raise ValueError("Semantic timeout must be between zero and 15 seconds.")
    if interpreter is not None:
        try:
            raw = await asyncio.wait_for(interpreter.interpret(request), timeout_seconds)
            value = SemanticInterpretation.model_validate(raw)
            validate_interpretation(value, request)
            return InterpretationResult(interpretation=value, origin="model")
        except Exception:
            # Provider text is neither evidence nor safe diagnostic output. No automatic retry.
            pass
    value = await AliasInterpreter().interpret(request)
    return InterpretationResult(
        interpretation=value, origin="fallback" if interpreter else "aliases"
    )
