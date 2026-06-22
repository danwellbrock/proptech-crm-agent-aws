from __future__ import annotations

import json
from typing import Any, Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph
from openai import OpenAI


class WorkflowState(TypedDict, total=False):
    lead: Dict[str, Any]
    model: str
    openai_api_key: str
    classification: str
    priority: str
    extractedFields: Dict[str, Any]
    missingFields: List[str]
    recommendedAction: str
    draftResponse: str
    requiresHumanApproval: bool
    riskNotes: List[str]


TRIAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "classification": {"type": "string", "enum": ["rental_enquiry", "sales_enquiry", "valuation_request", "maintenance_issue", "complaint", "unknown"]},
        "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
        "extractedFields": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "location": {"type": ["string", "null"]},
                "propertyType": {"type": ["string", "null"]},
                "budget": {"type": ["string", "null"]},
                "moveDate": {"type": ["string", "null"]},
                "availability": {"type": ["string", "null"]},
                "customerIntent": {"type": ["string", "null"]}
            },
            "required": ["location", "propertyType", "budget", "moveDate", "availability", "customerIntent"]
        },
        "missingFields": {"type": "array", "items": {"type": "string"}},
        "recommendedAction": {"type": "string"},
        "draftResponse": {"type": "string"},
        "requiresHumanApproval": {"type": "boolean"},
        "riskNotes": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["classification", "priority", "extractedFields", "missingFields", "recommendedAction", "draftResponse", "requiresHumanApproval", "riskNotes"]
}


def classify_and_extract(state: WorkflowState) -> WorkflowState:
    lead = state["lead"]
    client = OpenAI(api_key=state["openai_api_key"])

    system = (
        "You are a bounded CRM workflow agent for a PropTech company. "
        "You classify lead enquiries, extract useful CRM fields, identify missing information, "
        "and recommend a next action. You do not send messages or mutate a CRM. "
        "Any customer-facing action or CRM update must require human approval."
    )

    user = {
        "leadId": lead["leadId"],
        "source": lead["source"],
        "message": lead["message"],
        "customerEmail": lead.get("customerEmail"),
    }

    response = client.chat.completions.create(
        model=state["model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": "Triage this CRM lead enquiry and return only structured JSON.\n" + json.dumps(user, ensure_ascii=False)},
        ],
        response_format={"type": "json_schema", "json_schema": {"name": "proptech_crm_triage", "schema": TRIAGE_SCHEMA, "strict": True}},
        temperature=0.1,
    )

    parsed = json.loads(response.choices[0].message.content)
    return {**state, **parsed}


def enforce_policy(state: WorkflowState) -> WorkflowState:
    missing = state.get("missingFields", [])
    risk_notes = state.get("riskNotes", [])
    priority = state.get("priority", "normal")
    requires_approval = True

    if priority == "urgent":
        risk_notes = [*risk_notes, "Urgent lead requires human review before action."]
    if missing:
        risk_notes = [*risk_notes, "Missing fields must be resolved before CRM mutation."]

    return {**state, "requiresHumanApproval": requires_approval, "riskNotes": risk_notes}


def finalise(state: WorkflowState) -> WorkflowState:
    return state


def build_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("classify_and_extract", classify_and_extract)
    graph.add_node("enforce_policy", enforce_policy)
    graph.add_node("finalise", finalise)
    graph.add_edge(START, "classify_and_extract")
    graph.add_edge("classify_and_extract", "enforce_policy")
    graph.add_edge("enforce_policy", "finalise")
    graph.add_edge("finalise", END)
    return graph.compile()


def run_triage_graph(lead: Dict[str, Any], openai_api_key: str, model: str) -> Dict[str, Any]:
    compiled = build_graph()
    result = compiled.invoke({"lead": lead, "openai_api_key": openai_api_key, "model": model})
    return {
        "classification": result["classification"],
        "priority": result["priority"],
        "extractedFields": result["extractedFields"],
        "missingFields": result["missingFields"],
        "recommendedAction": result["recommendedAction"],
        "draftResponse": result["draftResponse"],
        "requiresHumanApproval": result["requiresHumanApproval"],
        "riskNotes": result["riskNotes"]
    }
