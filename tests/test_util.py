import json

from crm_agent.util import build_workflow_id, parse_event_body


def test_parse_event_body():
    event = {"body": json.dumps({"leadId": "1"})}
    assert parse_event_body(event)["leadId"] == "1"


def test_build_workflow_id_stable():
    payload = {"leadId": "1", "source": "x", "message": "hello"}
    assert build_workflow_id(payload) == build_workflow_id(payload)
