"""
bedrock.py — All communication with AWS Bedrock (the AI service).

This file handles two things:
  1. llm()   — Send a prompt to Nova LLM, get a text answer back
  2. embed() — Send text to Titan, get a list of 1024 numbers back (a vector)

Why the retry logic?
  AWS Bedrock has rate limits (throttling). If you send too many requests
  too fast, AWS returns a ThrottlingException. Instead of crashing, we
  wait and try again — starting at 5 seconds, doubling each time (5s, 10s, 20s...).
  This is called exponential backoff.
"""

import json
import time

import boto3
from botocore.exceptions import ClientError

from app.config import settings

# Cached Bedrock client — created once and reused for every call
_bedrock = None


def _client():
    """Return a Bedrock client, creating it once on first call."""
    global _bedrock
    if _bedrock is None:
        from botocore.config import Config
        # Disable botocore's own internal retry (max_attempts=1) so that
        # our custom backoff loop below is the only retry mechanism.
        # Without this, botocore retries 4x internally before we even see the error.
        cfg = Config(retries={"max_attempts": 1, "mode": "legacy"})
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=cfg,
        )
    return _bedrock


def _invoke_with_retry(model_id: str, body: dict, max_retries: int = 8) -> dict:
    """
    Call Bedrock with automatic retry on throttling errors.

    Waits 5s after first failure, 10s after second, 20s after third, etc.
    Raises the error immediately for non-throttling failures (e.g. bad request).
    """
    delay = 5.0  # starting wait in seconds
    throttle_codes = {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
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
                # Exponential backoff: 5s, 10s, 20s, 40s ...
                wait = delay * (2 ** attempt)
                print(f"  Throttled ({code}), waiting {wait:.0f}s "
                      f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                # Not a throttle error, or ran out of retries — raise immediately
                raise


def llm(prompt: str, system: str = "") -> str:
    """
    Send a prompt to the LLM and return the text response.

    Supports two model families:
    - Amazon Nova  → uses 'messages' + 'inferenceConfig' format
    - Anthropic Claude → uses 'anthropic_version' format

    The model family is detected automatically from the model ID in settings.
    """
    model = settings.bedrock_llm_model_id

    if "nova" in model or "amazon" in model.split(".")[0]:
        # Amazon Nova format: messages array with content blocks
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        body: dict = {"messages": messages, "inferenceConfig": {"maxTokens": 1024}}
        if system:
            # System prompt goes in a separate top-level key for Nova
            body["system"] = [{"text": system}]
        data = _invoke_with_retry(model, body)
        return data["output"]["message"]["content"][0]["text"]
    else:
        # Anthropic Claude format: anthropic_version header required
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        data = _invoke_with_retry(model, body)
        return data["content"][0]["text"]


def embed(text: str) -> list[float]:
    """
    Convert a piece of text (document chunk) into a vector of 1024 numbers.

    Used during ingestion — each policy chunk gets embedded and stored in pgvector.
    Uses 'search_document' input type for Cohere, standard format for Titan.
    """
    model = settings.bedrock_embed_model_id

    if model.startswith("cohere.embed"):
        # Cohere format: list of texts with input_type
        body = {"texts": [text], "input_type": "search_document"}
        data = _invoke_with_retry(model, body)
        return data["embeddings"][0]
    else:
        # Titan Embed v2 format
        body = {"inputText": text, "dimensions": settings.embed_dim, "normalize": True}
        data = _invoke_with_retry(model, body)
        return data["embedding"]


def embed_query(text: str) -> list[float]:
    """
    Convert a user's question into a vector for similarity search.

    Same as embed() but uses 'search_query' input type for Cohere —
    this tells the model the text is a search query, not a document,
    which improves retrieval accuracy.
    """
    model = settings.bedrock_embed_model_id

    if model.startswith("cohere.embed"):
        body = {"texts": [text], "input_type": "search_query"}
        data = _invoke_with_retry(model, body)
        return data["embeddings"][0]
    else:
        # Titan treats queries and documents the same way
        body = {"inputText": text, "dimensions": settings.embed_dim, "normalize": True}
        data = _invoke_with_retry(model, body)
        return data["embedding"]
