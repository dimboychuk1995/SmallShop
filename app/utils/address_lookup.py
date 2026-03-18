from __future__ import annotations

import json
import urllib.request
import urllib.parse

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "SmallShop/1.0 (address-autocomplete)"


def search_addresses(query: str, limit: int = 6, country_codes: str = "us") -> list[dict]:
    """
    Search address suggestions using the OpenStreetMap Nominatim API.
    Returns a list of dicts with keys: label, street, city, state, zip.
    """
    q = (query or "").strip()
    if len(q) < 3:
        return []

    params = urllib.parse.urlencode({
        "q": q,
        "format": "json",
        "addressdetails": 1,
        "limit": min(int(limit), 10),
        "countrycodes": country_codes,
    })

    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            results = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    suggestions = []
    for item in results:
        addr = item.get("address") or {}
        house_number = addr.get("house_number") or ""
        road = addr.get("road") or ""
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("hamlet")
            or ""
        )
        state = addr.get("state") or ""
        postcode = addr.get("postcode") or ""

        street = f"{house_number} {road}".strip()
        label_parts = [p for p in [street, city, state, postcode] if p]
        label = ", ".join(label_parts) or item.get("display_name") or ""

        suggestions.append({
            "label": label,
            "street": street,
            "city": city,
            "state": state,
            "zip": postcode,
        })

    return suggestions
