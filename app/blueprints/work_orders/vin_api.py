from __future__ import annotations

import json
import urllib.parse
import urllib.request

from flask import request, jsonify

from app.blueprints.work_orders import work_orders_bp
from app.utils.auth import login_required
from app.utils.permissions import permission_required


def _fetch_vpic(vin: str) -> dict:
    url = (
        "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/"
        f"{urllib.parse.quote(vin)}?format=json"
    )
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _extract_value(row: dict, keys: list[str]) -> str:
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


@work_orders_bp.get("/work_orders/api/vin")
@login_required
@permission_required("work_orders.create")
def api_decode_vin():
    vin = (request.args.get("vin") or "").strip().upper()
    if not vin:
        return jsonify({"ok": False, "error": "vin_required"}), 200

    if len(vin) != 17:
        return jsonify({"ok": False, "error": "vin_length", "message": "VIN must be exactly 17 characters"}), 200

    # Basic VIN validation - no I, O, or Q characters allowed
    if any(c in vin for c in ['I', 'O', 'Q']):
        return jsonify({"ok": False, "error": "vin_invalid_chars", "message": "VIN cannot contain I, O, or Q"}), 200

    try:
        payload = _fetch_vpic(vin)
    except Exception as e:
        print(f"[VIN API] Error fetching from VPIC: {e}")
        return jsonify({"ok": False, "error": "vin_lookup_failed", "message": "Failed to connect to VIN lookup service"}), 200

    results = payload.get("Results") if isinstance(payload, dict) else None
    if not results or not isinstance(results, list):
        return jsonify({"ok": False, "error": "vin_no_results", "message": "No results found for this VIN"}), 200

    row = results[0] if results else {}
    
    # Check if VIN was actually found (VPIC returns empty values if VIN is invalid)
    error_code = row.get("ErrorCode")
    if error_code and str(error_code) != "0":
        error_text = row.get("ErrorText", "Invalid VIN number")
        print(f"[VIN API] VPIC error for {vin}: {error_text}")
        return jsonify({"ok": False, "error": "vin_invalid", "message": error_text}), 200
    
    make = _extract_value(row, ["Make"])
    model = _extract_value(row, ["Model"])
    year = _extract_value(row, ["ModelYear", "Model Year", "Year"])
    vehicle_type = _extract_value(row, ["VehicleType", "Vehicle Type"])

    # Log successful lookup
    print(f"[VIN API] Successfully decoded {vin}: {year} {make} {model}")

    return jsonify(
        {
            "ok": True,
            "vin": vin,
            "make": make,
            "model": model,
            "year": year,
            "type": vehicle_type,
        }
    ), 200
