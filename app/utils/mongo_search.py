from __future__ import annotations

import re


def _safe_regex(raw: str) -> str:
    return re.escape(str(raw or "").strip())


def build_regex_search_filter(
    query: str,
    *,
    text_fields: list[str] | None = None,
    numeric_fields: list[str] | None = None,
    object_id_fields: list[str] | None = None,
) -> dict:
    """
    Builds a MongoDB filter for case-insensitive regex search across mixed field types.

    - `text_fields`: searched with plain `{field: /q/i}`
    - `numeric_fields`: searched via `$expr + $toString(field)`
    - `object_id_fields`: searched via `$expr + $toString(field)`

    Returns `{}` when query is empty.
    """
    q = str(query or "").strip()
    if not q:
        return {}

    regex = _safe_regex(q)
    clauses: list[dict] = []

    for field in (text_fields or []):
        clauses.append({field: {"$regex": regex, "$options": "i"}})

    for field in (numeric_fields or []):
        clauses.append(
            {
                "$expr": {
                    "$regexMatch": {
                        "input": {"$toString": {"$ifNull": [f"${field}", ""]}},
                        "regex": regex,
                        "options": "i",
                    }
                }
            }
        )

    for field in (object_id_fields or []):
        clauses.append(
            {
                "$expr": {
                    "$regexMatch": {
                        "input": {"$toString": {"$ifNull": [f"${field}", ""]}},
                        "regex": regex,
                        "options": "i",
                    }
                }
            }
        )

    if not clauses:
        return {}

    return {"$or": clauses}
