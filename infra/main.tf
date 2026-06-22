provider "aws" {
  region = var.aws_region
}

locals {
  name = var.project_name
}

resource "aws_dynamodb_table" "workflow_state" {
  name         = "${local.name}-workflow-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "workflow_id"

  attribute {
    name = "workflow_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = false
  }

  tags = { Project = local.name }
}

resource "aws_secretsmanager_secret" "openai" {
  name                    = "${local.name}/openai-api-key"
  description             = "OpenAI API key for ${local.name}. Value is set manually after deployment."
  recovery_window_in_days = 0
  tags                    = { Project = local.name }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}-triage"
  retention_in_days = 7
  tags              = { Project = local.name }
}

resource "aws_iam_role" "lambda" {
  name = "${local.name}-lambda-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = { Project = local.name }
}

resource "aws_iam_role_policy" "lambda" {
  name = "${local.name}-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem"
        ]
        Resource = aws_dynamodb_table.workflow_state.arn
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.openai.arn
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = [
          aws_sqs_queue.triage.arn,
          aws_sqs_queue.triage_dlq.arn
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "triage" {
  function_name                  = "${local.name}-triage"
  role                           = aws_iam_role.lambda.arn
  handler                        = "crm_agent.app.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  filename                       = "${path.module}/../build/lambda.zip"
  source_code_hash               = filebase64sha256("${path.module}/../build/lambda.zip")
  timeout                        = 30
  memory_size                    = 512
  reserved_concurrent_executions = 2

  environment {
    variables = {
      WORKFLOW_TABLE_NAME = aws_dynamodb_table.workflow_state.name
      OPENAI_SECRET_ARN   = aws_secretsmanager_secret.openai.arn
      OPENAI_MODEL        = var.openai_model
      DEMO_API_KEY        = var.demo_api_key
      TRIAGE_QUEUE_URL    = aws_sqs_queue.triage.url
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
  tags       = { Project = local.name }
}

resource "aws_apigatewayv2_api" "http" {
  name          = "${local.name}-http-api"
  protocol_type = "HTTP"
  tags          = { Project = local.name }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.triage.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "triage" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "POST /triage"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
  tags        = { Project = local.name }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.triage.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}


resource "aws_sqs_queue" "triage_dlq" {
  name                      = "${local.name}-triage-dlq"
  message_retention_seconds = 1209600

  tags = {
    Project = local.name
  }
}

resource "aws_sqs_queue" "triage" {
  name                       = "${local.name}-triage-queue"
  visibility_timeout_seconds = 120
  message_retention_seconds  = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.triage_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project = local.name
  }
}


resource "aws_lambda_event_source_mapping" "triage_sqs" {
  event_source_arn = aws_sqs_queue.triage.arn
  function_name    = aws_lambda_function.triage.arn
  batch_size       = 1
  enabled          = true
}
