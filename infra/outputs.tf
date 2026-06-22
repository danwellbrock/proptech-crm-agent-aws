output "api_endpoint" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "workflow_table_name" {
  value = aws_dynamodb_table.workflow_state.name
}

output "openai_secret_name" {
  value = aws_secretsmanager_secret.openai.name
}

output "openai_secret_arn" {
  value = aws_secretsmanager_secret.openai.arn
}

output "triage_queue_url" {
  value = aws_sqs_queue.triage.url
}

output "triage_dlq_url" {
  value = aws_sqs_queue.triage_dlq.url
}
