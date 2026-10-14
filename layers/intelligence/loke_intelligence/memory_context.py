"""Bound model context without changing canonical stored evidence or source records."""
import math

from loke_contracts.models import ContextBundle


def cost(context):
    return math.ceil(len(context.model_dump_json().encode("utf-8")) / 3)


def bounded_context(context: ContextBundle, budget=3000) -> ContextBundle:
    result = context.model_copy(deep=True)
    # Evidence/source excerpting is explicit; callers can retrieve originals by their stable IDs.
    for event in result.events:
        if len(event.text.encode()) > 512:
            event.text = event.text.encode()[:512].decode("utf-8", errors="ignore")
            result.context_truncated = True
    for source in result.sources:
        if len(source.text.encode()) > 1200:
            source.text = source.text.encode()[:1200].decode("utf-8", errors="ignore")
            result.context_truncated = True
    while cost(result) > budget:
        result.context_truncated = True
        if result.memory and any((result.memory.recent, result.memory.logs, result.memory.summaries)):
            groups = [g for g in (result.memory.recent, result.memory.logs, result.memory.summaries) if g]
            largest = max(groups, key=lambda g: sum(len(e.model_dump_json()) for e in g))
            largest.pop(0)
            result.memory.truncated = True
        elif result.events:
            result.events.pop(0)
        elif result.sources:
            result.sources.pop()
        elif result.memory and result.memory.matches:
            result.memory.matches.pop()
            result.memory.truncated = True
        else:
            raise ValueError("Required model state exceeds the context budget; clarify the scope.")
    return result
