import json
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any, Dict

import boto3

from crm_agent.graph import run_triage_graph
from crm_agent.persistence import WorkflowStore
from crm_agent.secrets import get_openai_api_key
from crm_agent.util import build_workflow_id, json_response, parse_event_body, require_fields

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs_client = boto3.client("sqs")


def _is_sqs_event(event: Dict[str, Any]) -> bool:
    return isinstance(event.get("Records"), list) and any(
        record.get("eventSource") == "aws:sqs" for record in event["Records"]
    )


def _check_demo_api_key(event: Dict[str, Any]) -> bool:
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    supplied_key = headers.get("x-demo-api-key")
    expected_key = os.environ.get("DEMO_API_KEY")
    return bool(expected_key and supplied_key == expected_key)


def _queue_triage_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, ["leadId", "source", "message"])

    workflow_id = build_workflow_id(payload)
    table_name = os.environ["WORKFLOW_TABLE_NAME"]
    queue_url = os.environ["TRIAGE_QUEUE_URL"]

    store = WorkflowStore(table_name)
    queued_at = datetime.now(timezone.utc).isoformat()

    queued_payload = {
        "workflowId": workflow_id,
        "status": "QUEUED",
        "leadId": payload["leadId"],
        "source": payload["source"],
        "queuedAt": queued_at,
        "lead": payload,
    }

    store.put_event(
        workflow_id=workflow_id,
        status="QUEUED",
        payload=queued_payload,
    )

    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(
            {
                "workflowId": workflow_id,
                "lead": payload,
            }
        ),
    )

    return queued_payload


def _process_triage_job(workflow_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, ["leadId", "source", "message"])

    table_name = os.environ["WORKFLOW_TABLE_NAME"]
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

    store = WorkflowStore(table_name)
    started_at = datetime.now(timezone.utc).isoformat()

    store.put_event(
        workflow_id=workflow_id,
        status="PROCESSING",
        payload={
            "workflowId": workflow_id,
            "lead": payload,
            "startedAt": started_at,
            "model": model,
        },
    )

    openai_api_key = get_openai_api_key(os.environ["OPENAI_SECRET_ARN"])

    result = run_triage_graph(
        lead=payload,
        openai_api_key=openai_api_key,
        model=model,
    )

    completed_at = datetime.now(timezone.utc).isoformat()

    output = {
        "workflowId": workflow_id,
        "status": "WAITING_FOR_HUMAN_APPROVAL"
        if result.get("requiresHumanApproval")
        else "READY",
        "leadId": payload["leadId"],
        "source": payload["source"],
        "completedAt": completed_at,
        "result": result,
    }

    store.put_event(
        workflow_id=workflow_id,
        status=output["status"],
        payload=output,
    )

    return output


def _handle_sqs_event(event: Dict[str, Any]) -> Dict[str, Any]:
    processed = []

    for record in event["Records"]:
        body = json.loads(record["body"])
        workflow_id = body["workflowId"]
        lead = body["lead"]

        logger.info("Processing workflow_id=%s lead_id=%s", workflow_id, lead.get("leadId"))

        output = _process_triage_job(workflow_id=workflow_id, payload=lead)
        processed.append(
            {
                "workflowId": workflow_id,
                "status": output["status"],
            }
        )

    return {
        "processed": processed,
        "count": len(processed),
    }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        if _is_sqs_event(event):
            return _handle_sqs_event(event)

        path = event.get("rawPath") or event.get("path") or "/"
        method = (
            event.get("requestContext", {})
            .get("http", {})
            .get("method", event.get("httpMethod", "GET"))
        )

        if path.endswith("/health"):
            return json_response(200, {"status": "ok"})

        if not path.endswith("/triage") or method.upper() not in {"POST", "ANY"}:
            return json_response(404, {"error": "not_found"})

        if not _check_demo_api_key(event):
            return json_response(401, {"error": "unauthorized"})

        payload = parse_event_body(event)
        queued_payload = _queue_triage_job(payload)

        return json_response(202, queued_payload)

    except ValueError as exc:
        return json_response(400, {"error": "bad_request", "message": str(exc)})
    except Exception as exc:
        logger.error("Unhandled error: %s", exc)
        logger.error(traceback.format_exc())
        return json_response(
            500,
            {
                "error": "internal_error",
                "message": "Workflow failed. Check CloudWatch logs.",
            },
        )
