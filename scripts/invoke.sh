#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${API_URL:-}" ]]; then
  echo "Set API_URL first, for example:"
  echo "export API_URL=\$(cd infra && tofu output -raw api_endpoint)"
  exit 1
fi

curl -s "$API_URL/triage" \
  -H 'content-type: application/json' \
  -d @"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/examples/lead_enquiry_001.json" | jq
