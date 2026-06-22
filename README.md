# PropTech CRM Agentic Workflow on AWS

A compact AWS reference implementation for a production-style agentic workflow using OpenAI, LangGraph, Lambda, SQS/DLQ, DynamoDB, Secrets Manager and API Gateway.

The project models a PropTech/CRM lead-triage workflow:

- Accept a lead enquiry through an HTTP API.
- Validate the request with a simple API key header.
- Queue the job for asynchronous processing.
- Run a LangGraph workflow inside Lambda.
- Use OpenAI for structured classification, extraction, risk notes and next-action drafting.
- Persist workflow state and audit output in DynamoDB.
- Stop at a human approval boundary before any customer-facing or CRM-mutating action.
- Capture failed jobs through an SQS dead-letter queue.

This is a small demo/reference project, not a production service.

## Architecture

```text
API Gateway HTTP API
  -> Lambda intake handler
  -> DynamoDB QUEUED state
  -> SQS triage queue
  -> Lambda worker invocation
  -> LangGraph workflow
  -> OpenAI structured output
  -> DynamoDB final state/audit output

Failed SQS retries
  -> SQS DLQ
```

## Components

- API Gateway HTTP API
- AWS Lambda, Python 3.12 arm64
- SQS queue for asynchronous job execution
- SQS DLQ for failed/poison messages
- DynamoDB workflow state/audit table
- AWS Secrets Manager for the OpenAI API key
- LangGraph for workflow orchestration
- OpenAI for structured CRM lead triage
- CloudWatch Logs for runtime evidence
- OpenTofu for infrastructure as code

## Workflow behaviour

The `/triage` endpoint accepts a lead enquiry payload, validates the API key, writes a queued workflow record, and sends the job to SQS.

The Lambda worker is invoked from SQS and runs the LangGraph workflow:

```text
START
  -> classify_and_extract
  -> enforce_policy
  -> finalise
  -> END
```

The OpenAI model stage returns structured output containing:

- classification
- priority
- extracted CRM fields
- missing fields
- risk notes
- recommended next action
- draft response
- human approval requirement

The policy stage enforces a human approval boundary before any customer-facing or CRM-mutating action.

## Example input

```json
{
  "leadId": "lead-001",
  "source": "Rightmove",
  "message": "Hi, I’m relocating to Bristol in August and need a 2-bed flat near Temple Meads. Budget around £1,700 pcm. Can view next week.",
  "customerEmail": "alex@example.com"
}
```

## Example queued response

```json
{
  "workflowId": "wf_c7b1188757983a860deede6f",
  "status": "QUEUED",
  "leadId": "lead-001",
  "source": "Rightmove",
  "queuedAt": "2026-06-22T20:51:42.458668+00:00"
}
```

## Example final state

The asynchronous worker updates DynamoDB with a final state similar to:

```json
{
  "workflowId": "wf_c7b1188757983a860deede6f",
  "status": "WAITING_FOR_HUMAN_APPROVAL",
  "leadId": "lead-001",
  "source": "Rightmove",
  "result": {
    "classification": "rental_enquiry",
    "priority": "normal",
    "extractedFields": {
      "location": "Bristol",
      "propertyType": "2-bed flat",
      "budget": "£1,700 pcm",
      "moveDate": "August",
      "availability": "next week",
      "customerIntent": "viewing"
    },
    "missingFields": [],
    "recommendedAction": "Contact the customer to confirm viewing appointment and provide suitable 2-bed flats near Temple Meads within budget.",
    "draftResponse": "Hi Alex, thank you for your enquiry...",
    "requiresHumanApproval": true,
    "riskNotes": []
  }
}
```

## Cost guardrails

The infrastructure deliberately avoids expensive always-on resources:

- No NAT Gateway
- No RDS
- No EC2
- No ECS/EKS
- No load balancer
- No OpenSearch
- DynamoDB uses PAY_PER_REQUEST
- Lambda is on-demand only
- API Gateway uses HTTP API
- CloudWatch log retention is set to 7 days
- Lambda reserved concurrency is capped

Set an AWS Budget before deploying.

## Prerequisites

Install local tooling:

```bash
brew install opentofu awscli jq
```

Docker is required for Lambda-compatible Python dependency packaging:

```bash
docker --version
```

Authenticate AWS:

```bash
aws sts get-caller-identity
```

Set the target region:

```bash
export AWS_REGION=eu-west-2
```

Set the AWS CLI profile if required:

```bash
export AWS_PROFILE=proptech-demo
```

Set the OpenAI API key only in your shell:

```bash
export OPENAI_API_KEY='sk-...'
```

Do not commit API keys, `.env` files, Terraform state, build artifacts or generated Lambda packages.

## Deploy

From the repo root:

```bash
./scripts/build_lambda.sh
cd infra
tofu init
```

Generate a simple demo API key for the `/triage` endpoint:

```bash
export DEMO_API_KEY="$(openssl rand -hex 24)"
```

Apply the infrastructure:

```bash
tofu apply -var="demo_api_key=$DEMO_API_KEY"
```

After apply, store the OpenAI key in Secrets Manager:

```bash
aws secretsmanager put-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$(tofu output -raw openai_secret_name)" \
  --secret-string "$OPENAI_API_KEY"
```

Export outputs for testing:

```bash
export API_URL="$(tofu output -raw api_endpoint)"
export TRIAGE_QUEUE_URL="$(tofu output -raw triage_queue_url)"
export TRIAGE_DLQ_URL="$(tofu output -raw triage_dlq_url)"
```

## Test

Health check:

```bash
curl -s "$API_URL/health" | jq
```

Expected:

```json
{
  "status": "ok"
}
```

Unauthenticated triage request should fail:

```bash
curl -s "$API_URL/triage" \
  -H 'content-type: application/json' \
  -d @../examples/lead_enquiry_001.json | jq
```

Expected:

```json
{
  "error": "unauthorized"
}
```

Authenticated triage request should queue the job:

```bash
curl -s "$API_URL/triage" \
  -H 'content-type: application/json' \
  -H "x-demo-api-key: $DEMO_API_KEY" \
  -d @../examples/lead_enquiry_001.json | jq
```

Expected status:

```json
"QUEUED"
```

After a few seconds, confirm the worker processed the job:

```bash
aws dynamodb scan \
  --region "$AWS_REGION" \
  --table-name "$(tofu output -raw workflow_table_name)" \
  --max-items 10 | jq
```

Look for:

```json
"WAITING_FOR_HUMAN_APPROVAL"
```

Check that the DLQ is empty:

```bash
aws sqs get-queue-attributes \
  --region "$AWS_REGION" \
  --queue-url "$TRIAGE_DLQ_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible | jq
```

Expected:

```json
{
  "Attributes": {
    "ApproximateNumberOfMessages": "0",
    "ApproximateNumberOfMessagesNotVisible": "0"
  }
}
```

View Lambda logs:

```bash
aws logs tail /aws/lambda/proptech-crm-agent-triage \
  --region "$AWS_REGION" \
  --since 10m
```

Useful evidence in the logs includes:

```text
Processing workflow_id=... lead_id=...
HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
```

## Run another example

```bash
curl -s "$API_URL/triage" \
  -H 'content-type: application/json' \
  -H "x-demo-api-key: $DEMO_API_KEY" \
  -d @../examples/lead_complaint_high_risk.json | jq
```

This exercises a higher-risk maintenance/complaint path and should still stop at human approval.

## Local validation

Install local test tooling if required:

```bash
python -m pip install pytest
```

Run the lightweight local tests:

```bash
python -m pytest tests -q
```

## Security notes

This is a demo project. It includes basic protection but is not production-hardened.

Current safeguards:

- OpenAI API key is stored in AWS Secrets Manager.
- `/triage` requires `x-demo-api-key`.
- Lambda reserved concurrency is capped.
- Workflow output is persisted to DynamoDB for auditability.
- The workflow stops before customer-facing or CRM-mutating action.
- SQS/DLQ provides retry isolation and failed-job capture.

Production improvements would include:

- Proper authorizer or IAM-authenticated API access
- WAF/rate limiting
- Structured correlation IDs
- Stronger idempotency model
- Separate intake and worker Lambdas
- Encrypted remote Terraform state
- CI/CD pipeline
- Centralised tracing
- Fine-grained IAM resource scoping
- Model evaluation and regression test set
- Explicit approval/rejection API

## Repository hygiene

Do not commit:

```text
infra/terraform.tfstate
infra/terraform.tfstate.backup
infra/.terraform/
build/
.env
real OpenAI API keys
real DEMO_API_KEY values
```

The `.gitignore` is configured to exclude generated build output and local Terraform state.

Before pushing to a public repo:

```bash
git status
git ls-files | grep -E 'terraform.tfstate|terraform.tfstate.backup|\.terraform/|build/|lambda.zip|OPENAI_API_KEY|DEMO_API_KEY' || true
git grep -n -E 'sk-[A-Za-z0-9_-]{20,}|DEMO_API_KEY=|OPENAI_API_KEY=|terraform.tfstate|secret_string|secret-string' || true
```

## Destroy

From `infra`:

```bash
tofu destroy -var="demo_api_key=$DEMO_API_KEY"
```

If the demo is no longer needed, also remove the IAM access key used for deployment.

## Summary

This project demonstrates a bounded, asynchronous agentic workflow on AWS:

```text
API Gateway -> Lambda intake -> SQS -> Lambda worker -> LangGraph/OpenAI -> DynamoDB
```

The design separates request intake from AI execution, stores workflow state/audit output, uses SQS/DLQ for retry and failure handling, and keeps human approval as the boundary before any external action.
