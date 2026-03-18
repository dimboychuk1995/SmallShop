from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import g, has_request_context, request, session

from app.extensions import get_master_db
from app.utils.auth import SESSION_TENANT_ID, SESSION_USER_ID


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SENSITIVE_KEYS = {
    "password",
    "pass",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
    "authorization",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_request_id() -> str:
    return uuid4().hex


def _safe_str(value, max_len: int = 1000) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _sanitize_payload(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            lower_key = str(key or "").strip().lower()
            if lower_key in SENSITIVE_KEYS:
                sanitized[key] = "***"
            else:
                sanitized[key] = _sanitize_payload(item)
        return sanitized

    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]

    if isinstance(value, tuple):
        return [_sanitize_payload(item) for item in value]

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return _safe_str(value, 2000)


def _get_request_payload() -> dict:
    payload: dict = {}

    json_data = request.get_json(silent=True)
    if isinstance(json_data, dict):
        payload["json"] = _sanitize_payload(json_data)

    form_data = request.form.to_dict(flat=False)
    if form_data:
        flattened = {k: (v[0] if len(v) == 1 else v) for k, v in form_data.items()}
        payload["form"] = _sanitize_payload(flattened)

    args_data = request.args.to_dict(flat=False)
    if args_data:
        flattened_args = {k: (v[0] if len(v) == 1 else v) for k, v in args_data.items()}
        payload["query"] = _sanitize_payload(flattened_args)

    return payload


def _resolve_user_tenant_context() -> tuple[str, str]:
    user_id = ""
    tenant_id = ""

    if getattr(g, "user", None):
        user_id = str(g.user.get("_id") or "")
    if getattr(g, "tenant", None):
        tenant_id = str(g.tenant.get("_id") or "")

    if not user_id:
        user_id = str(session.get(SESSION_USER_ID) or "")
    if not tenant_id:
        tenant_id = str(session.get(SESSION_TENANT_ID) or "")

    return user_id, tenant_id


def _resolve_shop_id(payload: dict) -> str:
    shop_id = str(session.get("shop_id") or "").strip()
    if shop_id:
        return shop_id

    for source_name in ("json", "form"):
        source = payload.get(source_name)
        if not isinstance(source, dict):
            continue

        for key in ("shop_id", "shopId", "location_id", "locationId"):
            value = source.get(key)
            if value:
                return str(value).strip()

    return ""


def should_log_current_request() -> bool:
    if not has_request_context():
        return False

    if request.method.upper() not in MUTATING_METHODS:
        return False

    if request.path.startswith("/static/"):
        return False

    return True


def write_audit_journal(response=None, error: Exception | None = None) -> None:
    if not should_log_current_request():
        return

    if getattr(g, "_audit_journal_written", False):
        return

    payload = _get_request_payload()
    user_id, tenant_id = _resolve_user_tenant_context()
    shop_id = _resolve_shop_id(payload)

    status_code = 500
    if response is not None:
        status_code = int(getattr(response, "status_code", 500) or 500)

    entry = {
        "request_id": str(getattr(g, "request_id", "") or build_request_id()),
        "created_at": utcnow(),
        "method": request.method.upper(),
        "path": request.path,
        "endpoint": str(request.endpoint or ""),
        "blueprint": str(request.blueprint or ""),
        "status_code": status_code,
        "ok": 200 <= status_code < 400,
        "ip": _safe_str(request.headers.get("X-Forwarded-For") or request.remote_addr or "", 255),
        "user_agent": _safe_str(request.headers.get("User-Agent") or "", 1024),
        "referrer": _safe_str(request.referrer or "", 1024),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "payload": payload,
        "error": _safe_str(error, 4000) if error else "",
    }

    try:
        master = get_master_db()
        master.audit_journal.insert_one(entry)
        g._audit_journal_written = True
    except Exception:
        pass
