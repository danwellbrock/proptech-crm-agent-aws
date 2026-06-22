from __future__ import annotations

import boto3


def get_openai_api_key(secret_arn: str) -> str:
    client = boto3.client("secretsmanager")
    result = client.get_secret_value(SecretId=secret_arn)
    value = result.get("SecretString")
    if not value:
        raise ValueError("OpenAI secret is empty or not configured")
    return value
