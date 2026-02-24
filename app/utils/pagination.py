from __future__ import annotations

import math


def _to_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def get_pagination_params(
    args,
    default_per_page: int = 20,
    max_per_page: int = 100,
    page_key: str = "page",
    per_page_key: str = "per_page",
) -> tuple[int, int]:
    page = _to_int(args.get(page_key), 1)
    per_page = _to_int(args.get(per_page_key), default_per_page)

    if page < 1:
        page = 1
    if per_page < 1:
        per_page = default_per_page
    if per_page > max_per_page:
        per_page = max_per_page

    return page, per_page


def paginate_find(collection, query: dict, sort: list[tuple[str, int]], page: int, per_page: int, projection: dict | None = None):
    total = collection.count_documents(query)
    pages = max(1, math.ceil(total / per_page)) if total else 1

    if page > pages:
        page = pages

    skip = (page - 1) * per_page

    cursor = collection.find(query, projection).sort(sort).skip(skip).limit(per_page)
    items = list(cursor)

    meta = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1 if page > 1 else 1,
        "next_page": page + 1 if page < pages else pages,
    }

    return items, meta
