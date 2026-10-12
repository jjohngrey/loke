import re


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def retrieve_chunks(query: str, sources: list[dict], limit: int = 2) -> list[dict]:
    words = tokens(query)
    ranked = [(len(words & tokens(source["text"])), source) for source in sources]
    return [
        source
        for score, source in sorted(ranked, key=lambda item: item[0], reverse=True)
        if score > 0
    ][:limit]
