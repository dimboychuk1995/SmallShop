from __future__ import annotations


def compact_search_text(value) -> str:
    if value is None:
        return ""
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def _trigram_tokens(compact_text: str) -> list[str]:
    if not compact_text:
        return []
    if len(compact_text) < 3:
        return [compact_text]
    return [compact_text[i:i + 3] for i in range(len(compact_text) - 2)]


def build_parts_search_terms(part_number: str | None, description: str | None, reference: str | None) -> list[str]:
    tokens = set()

    for raw in (part_number, description, reference):
        compact = compact_search_text(raw)
        if not compact:
            continue
        tokens.update(_trigram_tokens(compact))

    return sorted(tokens)


def build_query_tokens(query: str | None) -> tuple[str, list[str]]:
    normalized = compact_search_text(query)
    if not normalized:
        return "", []
    return normalized, _trigram_tokens(normalized)


def part_matches_query(query: str | None, part_number: str | None, description: str | None, reference: str | None) -> bool:
    normalized, _ = build_query_tokens(query)
    if not normalized:
        return False

    for raw in (part_number, description, reference):
        if normalized in compact_search_text(raw):
            return True

    return False
