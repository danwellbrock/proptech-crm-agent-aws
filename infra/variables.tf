variable "project_name" {
  type        = string
  description = "Project name used for AWS resource names."
  default     = "proptech-crm-agent"
}

variable "aws_region" {
  type        = string
  description = "AWS region."
  default     = "eu-west-2"
}

variable "openai_model" {
  type        = string
  description = "OpenAI model used by the Lambda workflow."
  default     = "gpt-4.1-mini"
}

variable "demo_api_key" {
  type        = string
  description = "Shared secret required by the /triage endpoint."
  sensitive   = true
}
