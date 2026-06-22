from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Dict, Iterable


def parse_event_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        raise ValueError("Request body is required")
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON body: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object")
    return parsed


def require_fields(payload: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [field for field in fields if not payload.get(field)]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def build_workflow_id(payload: Dict[str, Any]) -> str:
    stable = json.dumps({"leadId": payload.get("leadId"), "source": payload.get("source"), "message": payload.get("message")}, sort_keys=True)
    return "wf_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def json_response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status_code, "headers": {"content-type": "application/json"}, "body": json.dumps(payload, default=str)}
