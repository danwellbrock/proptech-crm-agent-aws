from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

import boto3


class WorkflowStore:
    def __init__(self, table_name: str):
        self.table = boto3.resource("dynamodb").Table(table_name)

    def put_event(self, workflow_id: str, status: str, payload: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.table.put_item(Item={"workflow_id": workflow_id, "status": status, "updated_at": now, "payload": json.loads(json.dumps(payload, default=str))})
