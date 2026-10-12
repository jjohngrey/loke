"""Deterministic activity selection and item assessment; models cannot override these."""

from datetime import UTC, datetime, timedelta

from loke_contracts.catalog import CARDS, CONCEPTS


def now(snapshot: dict) -> datetime:
    return datetime.now(UTC) + timedelta(hours=snapshot.get("demo_clock_hours", 0))


def match_concept(text: str) -> str | None:
    text = text.lower()
    ranked = [
        (sum(len(alias.split()) for alias in c["aliases"] if alias in text), c["id"])
        for c in CONCEPTS
    ]
    score, concept = max(ranked, key=lambda item: item[0])
    return concept if score else None


def card_for(concept_id: str, events: list[dict]) -> dict:
    pool = [c for c in CARDS if c["concept_id"] == concept_id]
    attempted = {e.get("card_id") for e in events if e["assessment"] != "not_assessed"}
    return next((c for c in pool if c["id"] not in attempted), pool[0])


def assess(card: dict, answer: str) -> str:
    normalized = answer.strip().lower().rstrip(".! ")
    if normalized in card["answers"]:
        return "correct"
    if card["kind"] == "mcq" and normalized.removeprefix("option ").upper() in card["options"]:
        return "incorrect"
    if card["kind"] == "blank" and normalized in {
        "na+",
        "sodium",
        "positive",
        "negative",
        "k+",
        "potassium",
    }:
        return "incorrect"
    return "ungraded"


def choose_plan(snapshot: dict) -> list[dict]:
    states = snapshot["states"]
    concepts = {c["id"]: c for c in CONCEPTS}
    eligible = []
    for concept_id, state in states.items():
        due = state.get("next_review_at")
        if due and datetime.fromisoformat(due) <= now(snapshot):
            eligible.append(
                (
                    "review",
                    concept_id,
                    "Scheduled review is due; this is not a claim that you forgot it.",
                    state["evidence_ids"],
                )
            )
    for concept_id, state in states.items():
        if state["status"] == "needs_practice":
            unchecked = [p for p in concepts[concept_id]["prerequisites"] if p not in states]
            for prerequisite in unchecked:
                eligible.append(
                    (
                        "diagnostic",
                        prerequisite,
                        f"This supports {concepts[concept_id]['label'].lower()}; we have not checked it yet.",
                        state["evidence_ids"],
                    )
                )
            eligible.append(
                (
                    "practice",
                    concept_id,
                    "One recorded item needs another practice check.",
                    state["evidence_ids"],
                )
            )
    if not eligible:
        eligible.append(
            (
                "diagnostic",
                "action_potential_phases",
                "Check a prerequisite before connecting it to transmitter release.",
                [],
            )
        )
    eligible.extend(
        [
            (
                "learn",
                "presynaptic_calcium_entry",
                "Connect neuronal signaling to calcium entry.",
                [],
            ),
            ("learn", "transmitter_release", "Connect the sequence to your learning goal.", []),
        ]
    )
    seen = set()
    result = []
    for kind, concept_id, reason, ids in eligible:
        if concept_id in seen:
            continue
        seen.add(concept_id)
        result.append(
            dict(
                kind=kind,
                concept_id=concept_id,
                title=concepts[concept_id]["label"],
                reason=reason,
                reason_event_ids=ids,
                minutes=max(1, min(2, snapshot.get("study_minutes", 10) // 3)),
            )
        )
        if len(result) == 3:
            break
    return result
