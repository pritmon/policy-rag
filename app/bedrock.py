import json
import time

import boto3
from botocore.exceptions import ClientError

from app.config import settings

_bedrock = None


def _client():
    global _bedrock
    if _bedrock is None:
        from botocore.config import Config
        # Disable botocore's internal retry so our backoff loop controls retries
        cfg = Config(retries={"max_attempts": 1, "mode": "legacy"})
        _bedrock = boto3.client("bedrock-runtime", region_name=settings.aws_region, config=cfg)
    return _bedrock


def _invoke_with_retry(model_id: str, body: dict, max_retries: int = 8) -> dict:
    delay = 5.0
    throttle_codes = {
        "ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException"
    }
    for attempt in range(max_retries):
        try:
            resp = _client().invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            return json.loads(resp["body"].read())
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in throttle_codes and attempt < max_retries - 1:
                wait = delay * (2 ** attempt)
                print(f"  Throttled ({code}), waiting {wait:.0f}s "
                      f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                raise


def llm(prompt: str, system: str = "") -> str:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    data = _invoke_with_retry(settings.bedrock_llm_model_id, body)
    return data["content"][0]["text"]


def embed(text: str) -> list[float]:
    model = settings.bedrock_embed_model_id
    if model.startswith("cohere.embed"):
        body = {"texts": [text], "input_type": "search_document"}
        data = _invoke_with_retry(model, body)
        return data["embeddings"][0]
    else:
        # Titan embed v2
        body = {"inputText": text, "dimensions": settings.embed_dim, "normalize": True}
        data = _invoke_with_retry(model, body)
        return data["embedding"]


def embed_query(text: str) -> list[float]:
    """Embed a query (search) rather than a document."""
    model = settings.bedrock_embed_model_id
    if model.startswith("cohere.embed"):
        body = {"texts": [text], "input_type": "search_query"}
        data = _invoke_with_retry(model, body)
        return data["embeddings"][0]
    else:
        body = {"inputText": text, "dimensions": settings.embed_dim, "normalize": True}
        data = _invoke_with_retry(model, body)
        return data["embedding"]
